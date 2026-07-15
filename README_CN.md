<p align="center">
  <a href="./README.md"><strong>简体中文</strong></a>
  ·
  <a href="./README_EN.md">English</a>
</p>

<h1 align="center">OCRA</h1>

<p align="center">
  <strong>Optical Collimation and Reference Assistant</strong><br>
  基于 ZWO ASI 与 USB/UVC 相机的望远镜光轴准直辅助软件
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12%2B-blue">
  <img alt="PyQt6" src="https://img.shields.io/badge/GUI-PyQt6-green">
  <img alt="OpenCV" src="https://img.shields.io/badge/Vision-OpenCV-orange">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows%2064--bit-lightgrey">
  <img alt="License" src="https://img.shields.io/badge/License-MPL--2.0-blueviolet">
</p>

## 项目背景与目的

OCRA 的开发初衷是为反射式望远镜用户提供一套开放、实用且更具性价比的相机辅助准直方案商业 OCAL 系统功能成熟，但完整硬件方案的购买成本较高，不一定适合预算有限的业余天文爱好者、学生和 DIY 用户

OCRA 尽可能利用用户已经拥有的 ZWO ASI 相机或普通 USB/UVC 相机，通过软件实现参考圆叠加、外圈自动吸附、圆心拟合和光轴偏差提示，从而减少购买专用准直硬件的额外成本，并降低相机辅助准直的使用门槛

> OCRA 是独立开发的开源项目，不是 OCAL 官方产品，也不与 OCAL 品牌或其制造商存在关联

## 项目简介

OCRA 是一款面向反射式望远镜光轴准直的桌面应用它通过 ZWO ASI 天文相机、普通 USB/UVC 相机或内置模拟相机获取实时画面，并叠加外圈、中圈、内圈、副镜参考圆、中心星标和偏移提示，帮助用户建立镜筒参考圆心、比较各光学结构的中心偏差并完成准直调节

用户连续点击三次 **“吸附外圈边缘”** 按钮后，程序会对三张独立视频帧执行边缘采样，保存每轮有效内点，并通过异常轮次剔除、RANSAC、Huber、MAD、条件数检测和联合几何圆拟合计算最终圆心与半径,整个流程不需要在画面上手动点击圆周点

---

## 主要功能

### 多相机支持

- **ZWO ASI 相机**：调用 `ASICamera2.dll`，支持设备枚举、曝光、增益、自动曝光和亮度偏置
- **USB/UVC 相机**：通过 OpenCV `VideoCapture` 读取普通摄像头、部分导星相机和免驱相机
- **模拟相机**：无需连接硬件即可测试界面、覆盖层、自动吸附和参数保存
- **QHY 相机**：当前仅保留后端接口，尚未接入 QHYCCD SDK，暂不可用于实际采集

### 严格三次外圈吸附

- 连续三次点击同一个 **“吸附外圈边缘”** 按钮
- 每次点击都会复制一张当前帧并执行一次完整、独立的外圈检测
- 按钮依次显示 `1/3`、`2/3` 和 `3/3`
- 第三次吸附结果会先完成显示，随后自动联合三轮有效边缘点，无需第四次点击
- 鼠标点击或拖动画面只用于改变下一次搜索初值，不会成为圆周采样点，也不会重置吸附次数
- 某一轮识别失败时，已完成的次数会保留，用户可以调整曝光、搜索位置、半径或边缘带宽后继续重试
- 点击 **“设为圆心”** 后，外圈参考中心被锁定，外圈吸附按钮及相关几何控制自动置灰
- 需要重新标定时，先点击 **“重置圆心”**

### 联合鲁棒圆拟合

外圈定位不是三点定圆，也不是简单平均三次圆心当前流程为：

1. 沿大量径向射线搜索外圈梯度边缘，必要时使用局部 Canny 环形边缘作为兜底
2. 每轮使用 RANSAC 寻找主圆并排除结构性错误边缘
3. 使用 Huber IRLS 按真实几何径向残差执行鲁棒精修
4. 使用 MAD 残差阈值执行点级异常值剔除
5. 比较三轮圆参数，排除明显不一致的一整轮采样
6. 平衡各轮点数并合并有效内点
7. 对联合点集再次执行鲁棒拟合和几何最小二乘精修
8. 使用圆周角度覆盖、归一化设计矩阵条件数和几何 Jacobian 条件数拒绝退化结果

条件数用于判断采样点是否集中在过短圆弧、圆心能否被稳定求解；它不是单点异常值检测方法真正的点级排异由 RANSAC、Huber 和 MAD 完成

### 光轴辅助调节

- 外圈、中圈、内圈和副镜参考圆独立设置
- 每个圆可单独启用并调整半径、线宽和颜色
- 中圈、内圈和副镜可单次吸附，也可启用持续吸附
- 中圈、内圈和副镜支持 **“与外圈同心”** 辅助显示
- 中心星标支持长度、线宽、角度和颜色调节
- HUD 显示检测得分、水平偏移、垂直偏移、距离和调节方向
- 可同时显示多个持续吸附目标的偏移信息
- 保存轻量历史数据，用于观察调节过程中的偏移变化

### 画面显示与性能

- 支持滑块和鼠标滚轮缩放
- 放大后支持水平和垂直平移
- 缩放围绕参考中心裁剪，检测坐标仍保持在原始相机坐标系中
- 视频线程采用单帧背压，只保留最新待显示帧，防止 Qt 事件队列长期积压
- UI 最大刷新帧率可配置，降低高分辨率和高倍率显示时的 CPU 压力
- 减少重复缩放、整帧复制和不必要的控件逐帧刷新

### 配置与界面

- 内置中文和英文界面切换
- 参数保存至可直接编辑的 `config/config.txt`
- 支持保存和重新读取相机、圆心、覆盖层、吸附及显示参数
- 相机参数采用防抖更新，避免输入过程中频繁调用相机 SDK

---

## 项目结构

```text
.
├─ main.py                         # 程序入口
├─ requirements.txt                # Python 依赖
├─ build_exe.bat                   # Windows EXE 一键打包脚本
├─ ASICamera2.dll                  # ZWO ASI SDK DLL（第三方组件）
├─ LICENSE                         # Mozilla Public License 2.0
├─ THIRD_PARTY_NOTICES.md          # 第三方组件声明
├─ README.md                       # 中文说明
├─ README_EN.md                    # English documentation
├─ config/
│  └─ config.txt                   # 用户配置文件
├─ cameras/
│  ├─ base_camera.py               # 相机统一接口
│  ├─ factory.py                   # 相机工厂与设备枚举
│  ├─ synthetic_camera.py          # 模拟相机
│  ├─ usb_camera.py                # USB/UVC 相机
│  ├─ zwo_camera.py                # ZWO ASI 相机
│  └─ qhy_camera.py                # QHY 预留接口
├─ core/
│  ├─ app_state.py                 # 全局配置与状态模型
│  ├─ config_manager.py            # 配置读写
│  ├─ i18n.py                      # 中英文文本
│  └─ vision_engine.py             # 检测、拟合、覆盖层和 HUD
└─ ui/
   ├─ interactive_label.py         # 视频画面鼠标交互
   ├─ main_window.py               # 主窗口与三次吸附状态机
   └─ video_thread.py              # 相机采集与单帧背压
```

---

## 环境要求

推荐环境：

- Windows 10/11 64 位
- Python 3.12 或 3.13，64 位
- PyQt6 6.6 及以上
- OpenCV 4.8 及以上
- NumPy 1.24 及以上
- Pillow 10.0 及以上

使用 ZWO ASI 相机还需要：

- 正确安装的 ZWO 相机驱动
- 64 位 `ASICamera2.dll`
- 相机未被 ASIStudio、SharpCap 或其他程序独占

> `ASI662MM-Pro.dll`、`ASI120MM.dll` 等型号或 DirectShow DLL 不是 SDK 入口OCRA 需要的是文件名为 `ASICamera2.dll` 的 SDK DLL

---

## 基本使用流程

### 1. 连接相机

1. 在右侧面板选择相机类型
2. 刷新并选择实际设备
3. 设置分辨率、曝光、亮度偏置、增益或 USB 对焦参数
4. 确认实时画面能够稳定显示

### 2. 粗调外圈参考圆

使用鼠标、圆心偏移滑块和半径控制，将外圈参考圆大致移动到镜筒外缘附近此时不要求完全重合，只需确保搜索带能够覆盖真实外圈边缘

### 3. 完成三次外圈吸附

连续点击三次 **“吸附外圈边缘”**：

```text
第一次 → 独立采样与拟合 → 1/3
第二次 → 独立采样与拟合 → 2/3
第三次 → 独立采样与拟合 → 3/3
       → 自动联合三轮有效边缘点
       → 输出最终圆心和半径
```

如果某次识别失败，已成功次数会保留调整曝光、外圈初始位置、半径或边缘带宽后，再次点击同一个按钮重试当前轮次

如果三轮结果不一致、角度覆盖不足或条件数过高，程序会拒绝不可靠结果，并恢复本轮开始前的外圈位置

### 4. 锁定参考圆心

确认外圈参考圆与镜筒边缘贴合后，点击 **“设为圆心”**锁定后：

- 外圈参考中心成为准直基准
- 外圈吸附按钮自动置灰
- 外圈位置和半径不可继续修改
- 颜色和线宽仍可调整，因为它们不会改变参考几何

需要重新标定时，点击 **“重置圆心”**

### 5. 吸附其他结构

根据实际镜筒画面选择：

- **吸附中圈边缘**
- **吸附内圈小圆边缘**
- **吸附副镜边缘**
- **持续吸附**
- **与外圈同心**

观察 HUD 中的 `dx`、`dy`、距离和 Guide 提示，调节机械结构，使目标中心逐渐接近外圈参考圆心

---

## 常用配置

配置文件位于 `config/config.txt`：

| 参数 | 说明 |
|---|---|
| `camera_type` | `synthetic`、`usb`、`zwo` 或 `qhy` |
| `camera_id` | 当前设备编号 |
| `frame_width` / `frame_height` | 相机采集分辨率 |
| `camera_exposure_ms` | 曝光参数 |
| `camera_iso` | ZWO OFFSET 或 USB ISO/亮度 |
| `camera_gain` | 相机增益 |
| `camera_auto_exposure` | 自动曝光 |
| `camera_auto_focus` / `camera_focus` | USB 相机电子对焦参数 |
| `zwo_dll_path` | 手动指定 `ASICamera2.dll` 路径，可留空自动搜索 |
| `ui_fps_limit` | UI 最大刷新帧率 |
| `zoom_percent` | 显示缩放比例 |
| `edge_band_width` | 通用边缘搜索带宽 |
| `secondary_edge_band_width` | 副镜边缘搜索带宽 |
| `secondary_edge_sensitivity` | 副镜弱边缘灵敏度 |
| `guide_tolerance` | Guide 判定允许偏差 |

不确定参数含义时，建议优先通过界面调整并点击 **“保存参数”**，不要直接手工修改配置文件

---

## 打包 Windows EXE

项目提供 `build_exe.bat`，使用 PyInstaller 的 `onedir` 模式构建 Windows 程序

### 一键打包

直接双击：

```text
build_exe.bat
```

或在项目目录的 CMD 中运行：

```bat
build_exe.bat
```

脚本会自动：

1. 检查 64 位 Python 3.13、3.12 或默认 Python
2. 创建或复用 `.venv`
3. 安装项目依赖和 PyInstaller
4. 清理旧的 `build` 与 `dist`
5. 打包 `config` 和可选的 `ASICamera2.dll`
6. 生成无控制台窗口的程序

构建结果位于：

```text
dist\OCRA\OCRA.exe
```

发布时必须复制整个目录：

```text
dist\OCRA\
```

不能只复制 `OCRA.exe`，因为 PyQt6、OpenCV、Python Runtime、配置文件和相机 DLL 等运行文件位于同一程序目录中

---

## 常见问题

### 外圈为什么需要吸附三次？

三次点击分别对三张固定视频帧执行独立采样第三次完成后，程序检查三轮一致性并联合全部有效边缘内点，从而降低单帧噪声、反光、遮挡或偶发错误边缘对最终圆心的影响

### 鼠标点击画面会记录圆周点吗？

不会鼠标只用于移动搜索初值或平移放大画面，不参与三点定圆，也不会清空 `1/3` 或 `2/3` 进度

### 为什么显示“角度覆盖不足”或“拟合矩阵病态”？

这表示有效边缘点集中在过短圆弧即使局部残差较小，这种几何条件也无法稳定确定圆心请调整外圈位置、半径、曝光或边缘带宽，让程序识别到更完整的镜筒圆周

### 为什么 USB 相机的曝光、ISO 或对焦没有反应？

OpenCV/UVC 控制项取决于具体相机和驱动部分设备不支持某些参数，或者参数量纲与界面值并非一一对应程序会尝试写入，不支持时安全忽略

### 为什么找不到 ZWO 相机？

请检查：

- 已安装 ZWO 官方驱动
- 使用 64 位 Python 或 64 位 EXE
- `ASICamera2.dll` 是兼容的 64 位 SDK DLL
- 相机未被其他软件占用
- USB 数据线和供电正常

### 放大运行一段时间后仍然掉帧怎么办？

建议：

- 将 `ui_fps_limit` 设置为 10–20 FPS
- 降低相机分辨率
- 减小显示窗口尺寸或缩放倍率
- 关闭不需要的持续吸附目标
- 检查曝光时间是否已经高于目标帧间隔

---

## 开发说明

项目采用相机层、状态层、视觉算法层和 UI 层分离设计：

- 新增相机后端时，实现 `BaseCamera` 接口并在 `cameras/factory.py` 注册
- 配置字段统一定义在 `core/app_state.py`
- 中英文界面文本统一维护在 `core/i18n.py`
- 圆拟合、HUD 和覆盖层逻辑位于 `core/vision_engine.py`
- 主窗口交互和三次外圈吸附状态机位于 `ui/main_window.py`

QHY 后端目前是占位实现欢迎基于 QHYCCD SDK 完成设备枚举、参数控制和视频采集

---

## 精度与使用限制

- OCRA 是准直辅助工具，最终结果仍会受到镜头畸变、相机安装倾斜、机械偏心、镜筒边缘非圆、反光和对焦状态影响
- 拟合残差较小不一定代表真实机械轴完全准确，建议结合相机旋转复测和实际星点测试验证
- 在边缘清晰、圆周覆盖充分的情况下，算法可实现亚像素级重复定位；真实机械绝对误差还取决于光学与安装条件
- 条件数和角度覆盖检测会拒绝明显退化的短圆弧结果，避免输出看似正常但实际不可靠的圆心

---

## License

OCRA 的原创源代码采用 **Mozilla Public License 2.0（MPL-2.0）** 发布你可以使用、修改和分发本项目，但对 MPL 覆盖文件的修改在分发时仍需提供对应源代码并保留许可证声明完整条款见 [`LICENSE`](./LICENSE)

`ASICamera2.dll`、相机 SDK、Python 依赖及其他第三方组件不属于 OCRA 原创源代码，也不自动受 MPL-2.0 覆盖它们分别遵守各自的许可证或分发条款，详情见 [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md)

> 在公开分发包含 `ASICamera2.dll` 的源码包或 EXE 之前，请确认当前 ZWO SDK 条款允许你的具体分发方式若无法确认，可不在仓库中提交该 DLL，并要求用户自行从官方 SDK 获取
