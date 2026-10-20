# ASUS RGB for Linux

独立的 ASUS RGB 桌面控制工具：原生访问 OMNI、Aura USB 和已识别的 ENE
内存灯光控制器，无需安装或运行 OpenRGB。

## 功能

- 图形界面统一管理支持的键盘、鼠标、主板 ARGB、内存、Throne Qi 和 Aura Terminal。
- 常亮、呼吸、色彩循环与逐灯珠彩虹流动。
- 自定义 2–16 个渐变颜色，支持调整顺序、颜色选择器和渐变预览。
- 自定义流动速度：一轮 1–60 秒，秒数越小越快。
- 自动保存模式、颜色、亮度、渐变列表和速度；下次启动恢复。
- systemd 用户后台服务：关闭界面仍保持灯效，休眠设备单独重试。
- 按字体计算设备列表行高，支持横向和纵向滚动。

## 安装

要求：Linux、Python 3.10+、systemd 和 Tk。运行时仅使用 Python 标准库。
在 Debian/Ubuntu 安装图形界面依赖：

```bash
sudo apt install python3 python3-tk
```

下载或克隆源码，进入项目目录。先安装硬件访问规则：

```bash
sudo install -m 644 scripts/70-asus-rgb.rules /etc/udev/rules.d/70-asus-rgb.rules
sudo udevadm control --reload-rules
sudo udevadm trigger --subsystem-match=hidraw
sudo udevadm trigger --subsystem-match=i2c-dev
```

以正常桌面用户安装启动器、应用菜单入口和后台服务：

```bash
python3 scripts/install-user.py
```

安装脚本根据当前源码目录、用户目录和 Python 路径生成本地配置，不包含固定用户名。
源码目录必须保留；移动后重新运行安装脚本即可，现有灯光配置不会被覆盖。
如需仅安装文件而不启动服务，使用 `--no-start`。

默认登录时启动。需要用户服务在登录前启动、退出桌面后仍驻留时，可选择：

```bash
loginctl enable-linger "$USER"
```

设备规则默认授予活动本地会话权限。无登录的运行环境需要另行配置适当的设备权限。
AMD 内存控制还要求内核暴露对应的 PIIX4 I²C/SMBus 总线。

## 使用

在应用菜单搜索 **ASUS RGB**，或运行：

```bash
asus-rgb gui
```

选择 **彩虹流动**，在“彩虹颜色”中填写色值或点击“添加颜色”，调整“流动一轮”，
最后点击 **应用到全部并保存**。色值可用空格或逗号分隔，例如：

```text
#00aaff #bb00ff #ff0088
```

配置保存在当前用户的 `~/.config/asus-rgb/profile.json`，不随源码发布。

命令行示例：

```bash
asus-rgb scan
asus-rgb set ffffff --brightness 70 --mode static --save
asus-rgb set ffffff --mode rainbow --palette '00aaff bb00ff ff0088' --period 8 --save
asus-rgb restore
systemctl --user status asus-rgb.service
systemctl --user stop asus-rgb.service
systemctl --user disable --now asus-rgb.service
```

## 当前支持范围

| 控制器 | 原生控制路径 |
|---|---|
| 支持的 Azoth 系列键盘 | OMNI 配对识别、逐键更新、确认消息校验 |
| Harpe Ace Extreme 鼠标 | OMNI，滚轮单区随渐变颜色变化 |
| ASUS Aura USB 主板控制器 | 每个 ARGB 接口的逐灯珠更新 |
| Aura Terminal | 多接口逐灯珠更新 |
| Throne Qi | GHS80 `0b05:18c5` 灯光接口；不使用其独立音频接口 |
| 已识别的 ENE DRAM 控制器 | PIIX4 内存总线、身份检查、逐字节寄存器更新 |

这些是当前实现覆盖的协议和设备标识，不表示所有固件版本均已验证。未识别的设备
不会收到灯光写入。安装脚本及 CI 不执行硬件写入。

## 限制与验证

- 彩虹动画由后台服务生成；关闭整个服务后不再继续生成新帧。
- 不同物理灯条的方向、长度和设备传输时延会影响视觉效果。当前 ARGB 每个接口
  按 120 颗灯珠发送；单区鼠标无法展示空间渐变。
- 内存更新限制为 **每秒 2 次**，会比 USB 灯条更有步进感；不使用 SMBus 块写入。
- 不访问 SPD、不重映射内存控制器地址、不写固件或灯光闪存。
- 内存首帧读回验证；键盘和 Throne 检查确认消息。部分 USB 设备没有颜色读回，
  因此“指令已发送”不等同于目视验证。
- 自动化测试覆盖颜色解析、循环渐变、亮度、速度、配置记忆、设备路由、数据包长度、
  并发接口回复和独立重试。短时硬件验证不能代替长期稳定性测试。

```bash
python3 -m unittest discover -v
```

## 隐私

工具不包含遥测或云服务依赖，原生控制和配置保存在本机。发布内容仅包括源码、
通用设备 ID、合成测试数据、文档和安装文件，不包含个人配置、设备序列号、
系统诊断日志、令牌、用户目录或本地虚拟环境。

源码保留一个可选的旧 OpenRGB SDK 客户端兼容模块，默认不使用，也不自动连接它。

## 许可证与来源

GPL-3.0-or-later，见 [LICENSE](LICENSE)。本项目与 ASUS 无隶属关系。
公开协议参考和致谢见 [NOTICE](NOTICE)。
