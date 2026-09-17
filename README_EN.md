<p align="center">
  <a href="./README.md"><strong>Simplified Chinese</strong></a>
  ·
  <a href="./README_EN.md">English</a>
</p>

<h1 align="center">OCRA</h1>

<p align="center">
  <strong>Optical Collimation and Reference Assistant</strong><br>
  A telescope optical-axis collimation assistant for ZWO ASI and USB/UVC cameras
</p>

<p align="center">
  <img alt="Python" src="https://img.shields.io/badge/Python-3.12%2B-blue">
  <img alt="PyQt6" src="https://img.shields.io/badge/GUI-PyQt6-green">
  <img alt="OpenCV" src="https://img.shields.io/badge/Vision-OpenCV-orange">
  <img alt="Platform" src="https://img.shields.io/badge/Platform-Windows%2064--bit-lightgrey">
  <img alt="License" src="https://img.shields.io/badge/License-MPL--2.0-blueviolet">
</p>

## Project Background and Purpose

OCRA was developed to provide reflector telescope users with an open, practical, and more cost-effective camera-assisted collimation solution Commercial OCAL systems are mature in functionality, but the complete hardware solution is relatively expensive and may not be suitable for amateur astronomers, students, and DIY users with limited budgets

OCRA makes use of ZWO ASI cameras or standard USB/UVC cameras that users may already own whenever possible, implementing reference-circle overlays, automatic outer-edge snapping, center fitting, and optical-axis deviation guidance through software, thereby reducing the additional cost of purchasing dedicated collimation hardware and lowering the barrier to camera-assisted collimation

> OCRA is an independently developed open-source project It is not an official OCAL product and is not affiliated with the OCAL brand or its manufacturer

## Project Overview

OCRA is a desktop application designed for optical-axis collimation of reflector telescopes It acquires live images through ZWO ASI astronomy cameras, standard USB/UVC cameras, or the built-in simulated camera, and overlays outer-circle, middle-circle, inner-circle, and secondary-mirror reference circles, a center marker, and offset guidance to help users establish the telescope tube reference center, compare center deviations among optical structures, and complete collimation adjustments

After the user clicks the **“Snap Outer Edge”** button three consecutive times, the program performs edge sampling on three independent video frames, saves the valid inliers from each pass, and calculates the final center and radius through abnormal-pass rejection, RANSAC, Huber, MAD, condition-number detection, and joint geometric circle fitting,the entire process does not require manually clicking points on the circumference in the image

---

## Main Features

### Multi-Camera Support

- **ZWO ASI cameras**: Calls `ASICamera2.dll` and supports device enumeration, exposure, gain, automatic exposure, and brightness offset
- **USB/UVC cameras**: Uses OpenCV `VideoCapture` to access standard webcams, some guide cameras, and driverless cameras
- **Simulated camera**: Tests the interface, overlays, automatic snapping, and parameter saving without connecting hardware
- **QHY cameras**: Only a backend interface is currently reserved The QHYCCD SDK has not yet been integrated, so actual capture is not currently available

### Strict Three-Pass Outer-Edge Snapping

- Click the same **“Snap Outer Edge”** button three consecutive times
- Each click copies the current frame and performs one complete and independent outer-edge detection
- The button displays `1/3`, `2/3`, and `3/3` in sequence
- The third snapping result is displayed first, after which the valid edge points from all three passes are automatically combined No fourth click is required
- Clicking or dragging in the image only changes the initial search position for the next pass It does not create circumference sample points or reset the snapping count
- If recognition fails during one pass, the completed count is retained The user can adjust exposure, search position, radius, or edge-band width and continue retrying
- After clicking **“Set as Center”**, the outer reference center is locked, and the outer-edge snapping button and related geometry controls are automatically disabled
- To recalibrate, click **“Reset Center”** first

### Joint Robust Circle Fitting

Outer-circle positioning is neither a three-point circle calculation nor a simple average of three circle centers The current process is:

1. Search for outer-circle gradient edges along a large number of radial rays, using local Canny annular edges as a fallback when necessary
2. Use RANSAC in each pass to find the primary circle and reject structurally incorrect edges
3. Use Huber IRLS to perform robust refinement based on true geometric radial residuals
4. Use a MAD residual threshold for point-level outlier rejection
5. Compare the circle parameters from the three passes and reject an entire pass that is clearly inconsistent
6. Balance the number of points from each pass and merge the valid inliers
7. Perform robust fitting and geometric least-squares refinement again on the combined point set
8. Reject degenerate results using circumferential angular coverage, the condition number of the normalized design matrix, and the condition number of the geometric Jacobian

The condition number is used to determine whether sample points are concentrated on an excessively short arc and whether the center can be solved stably; it is not a point-level outlier detection method Actual point-level rejection is performed by RANSAC, Huber, and MAD

### Optical-Axis Adjustment Assistance

- Outer-circle, middle-circle, inner-circle, and secondary-mirror reference circles can be configured independently
- Each circle can be enabled separately and its radius, line width, and color can be adjusted
- The middle circle, inner circle, and secondary mirror support both one-time snapping and continuous snapping
- The middle circle, inner circle, and secondary mirror support **“Concentric with Outer Circle”** assisted display
- The center marker supports adjustment of length, line width, angle, and color
- The HUD displays detection score, horizontal offset, vertical offset, distance, and adjustment direction
- Offset information for multiple continuously snapped targets can be displayed simultaneously
- Lightweight historical data are saved to observe offset changes during adjustment

### Image Display and Performance

- Supports zooming with a slider and the mouse wheel
- Supports horizontal and vertical panning after zooming in
- Zooming crops around the reference center while detection coordinates remain in the original camera coordinate system
- The video thread uses single-frame backpressure and retains only the latest frame waiting to be displayed, preventing long-term accumulation in the Qt event queue
- The maximum UI refresh frame rate is configurable to reduce CPU load during high-resolution and high-magnification display
- Reduces repeated scaling, full-frame copying, and unnecessary per-frame control refreshes

### Configuration and Interface

- Built-in Chinese and English interface switching
- Parameters are saved to the directly editable `config/config.txt`
- Supports saving and reloading camera, center, overlay, snapping, and display parameters
- Camera parameters use debounced updates to avoid frequent camera SDK calls during input

---

## Project Structure

```text
.
├─ main.py                         # Program entry point
├─ requirements.txt                # Python dependencies
├─ py_build/
│  ├─ build_exe.bat                # Windows folder-distribution build script
│  ├─ build_single_exe.bat         # Windows single-file build script
│  └─ OCRA_icon.ico                # Application icon
├─ ASICamera2.dll                  # ZWO ASI SDK DLL (third-party component)
├─ LICENSE                         # Mozilla Public License 2.0
├─ THIRD_PARTY_NOTICES.md          # Third-party component notices
├─ README.md                       # Chinese documentation
├─ README_EN.md                    # English documentation
├─ config/
│  └─ config.txt                   # User configuration file
├─ cameras/
│  ├─ base_camera.py               # Unified camera interface
│  ├─ factory.py                   # Camera factory and device enumeration
│  ├─ synthetic_camera.py          # Simulated camera
│  ├─ usb_camera.py                # USB/UVC camera
│  ├─ zwo_camera.py                # ZWO ASI camera
│  └─ qhy_camera.py                # Reserved QHY interface
├─ core/
│  ├─ app_state.py                 # Global configuration and state model
│  ├─ config_manager.py            # Configuration reading and writing
│  ├─ i18n.py                      # Chinese and English text
│  └─ vision_engine.py             # Detection, fitting, overlays, and HUD
└─ ui/
   ├─ interactive_label.py         # Mouse interaction with the video image
   ├─ main_window.py               # Main window and three-pass snapping state machine
   └─ video_thread.py              # Camera capture and single-frame backpressure
```

---

## Requirements

Recommended environment:

- Windows 10/11 64-bit
- Python 3.12 or 3.13, 64-bit
- PyQt6 6.8.1
- OpenCV 4.8 or later
- NumPy 1.24 or later
- Pillow 10.0 or later

Using a ZWO ASI camera also requires:

- Properly installed ZWO camera drivers
- A 64-bit `ASICamera2.dll`
- The camera is not exclusively occupied by ASIStudio, SharpCap, or another program

> Model-specific or DirectShow DLLs such as `ASI662MM-Pro.dll` and `ASI120MM.dll` are not SDK entry points OCRA requires the SDK DLL named `ASICamera2.dll`

---

## Switching Serena Environments

Serena now uses an independent local environment selection instead of depending on the `.venv` junction in the project root. Switching the runtime environment therefore does not affect code indexing or import diagnostics.

List environments under `D:\miniconda3\envs`:

```powershell
.\.serena\select_python_env.ps1 -List
```

Select the environment Serena should use for analysis:

```powershell
.\.serena\select_python_env.ps1 -Name Python3.13
```

The selection is stored in the ignored `.serena/python-env.local.json` file, and the generated `pyrightconfig.json` is also excluded from Git. Every Serena project activation validates the selected environment and refreshes the configuration automatically.

If the selected environment lacks PyQt6, OpenCV, NumPy, or Pillow, the switch is rejected and the last valid environment remains active. Install `requirements.txt` as directed by the error message, then switch again.

For another environment root, pass `-EnvRoot` or set the `SERENA_ENV_ROOT` and `SERENA_PYTHON_ENV` environment variables. If diagnostics remain stale after a switch, reactivate the OCRA project once.

---

## Basic Usage Workflow

### 1. Connect the Camera

1. Select the camera type in the right-side panel
2. Refresh and select the actual device
3. Set the resolution, exposure, brightness offset, gain, or USB focus parameters
4. Confirm that the live image is displayed stably

### 2. Roughly Adjust the Outer Reference Circle

Use the mouse, center-offset sliders, and radius control to move the outer reference circle approximately near the outer edge of the telescope tube Exact alignment is not required at this stage You only need to ensure that the search band covers the actual outer edge

### 3. Complete Three-Pass Outer-Edge Snapping

Click **“Snap Outer Edge”** three consecutive times:

```text
First pass  → Independent sampling and fitting → 1/3
Second pass → Independent sampling and fitting → 2/3
Third pass  → Independent sampling and fitting → 3/3
            → Automatically combine valid edge points from all three passes
            → Output the final center and radius
```

If recognition fails during one pass, the number of successful passes is retained Adjust the exposure, initial outer-circle position, radius, or edge-band width, then click the same button again to retry the current pass

If the three-pass results are inconsistent, the angular coverage is insufficient, or the condition number is too high, the program rejects the unreliable result and restores the outer-circle position from before the current sequence began

### 4. Lock the Reference Center

After confirming that the outer reference circle matches the telescope tube edge, click **“Set as Center”**After locking:

- The outer reference center becomes the collimation reference
- The outer-edge snapping button is automatically disabled
- The outer-circle position and radius can no longer be modified
- The color and line width can still be adjusted because they do not change the reference geometry

To recalibrate, click **“Reset Center”**

### 5. Snap Other Structures

Select according to the actual telescope image:

- **Snap Middle-Circle Edge**
- **Snap Inner Small-Circle Edge**
- **Snap Secondary-Mirror Edge**
- **Continuous Snapping**
- **Concentric with Outer Circle**

Observe `dx`, `dy`, distance, and Guide prompts in the HUD, and adjust the mechanical structure so that the target center gradually approaches the outer reference center

---

## Common Configuration

The configuration file is located at `config/config.txt`:

| Parameter | Description |
|---|---|
| `camera_type` | `synthetic`, `usb`, `zwo`, or `qhy` |
| `camera_id` | Current device number |
| `frame_width` / `frame_height` | Camera capture resolution |
| `camera_exposure_ms` | Exposure parameter |
| `camera_iso` | ZWO OFFSET or USB ISO/brightness |
| `camera_gain` | Camera gain |
| `camera_auto_exposure` | Automatic exposure |
| `camera_auto_focus` / `camera_focus` | USB camera electronic focus parameters |
| `zwo_dll_path` | Manually specifies the path to `ASICamera2.dll` It can be left blank for automatic search |
| `ui_fps_limit` | Maximum UI refresh frame rate |
| `zoom_percent` | Display zoom percentage |
| `edge_band_width` | General edge-search band width |
| `secondary_edge_band_width` | Secondary-mirror edge-search band width |
| `secondary_edge_sensitivity` | Secondary-mirror weak-edge sensitivity |
| `guide_tolerance` | Allowed deviation for Guide judgment |

If you are unsure about the meaning of a parameter, it is recommended to adjust it through the interface and click **“Save Parameters”** instead of editing the configuration file manually

---

## Packaging a Windows EXE

The project provides two general-purpose PyInstaller scripts:

- `py_build/build_exe.bat`: folder distribution with faster startup; distribute the entire `py_build/dist/OCRA` directory
- `py_build/build_single_exe.bat`: single-file distribution that extracts to a temporary directory during startup

By default, the scripts select the build environment in this order:

1. Reuse the dedicated lightweight `py_build/.build_env` environment
2. If it does not exist, create it with the interpreter specified by `OCRA_BUILD_PYTHON`
3. Otherwise try `D:\miniconda3\envs\Python3.13\python.exe` or another available 64-bit Python installation

The dedicated environment prevents unused components such as MKL from a full Conda environment from entering the release. Custom hooks also exclude the unused FFmpeg video-file codec bundle and Pillow image plug-ins without affecting USB cameras, ASI cameras, screenshots, or interface rendering.

When the base interpreter comes from Conda, the shared `py_build/build_runtime.py` entry point registers that interpreter's `Library/bin` and `DLLs` directories. PyInstaller recursively collects libraries actually referenced by the application, including `ffi-8.dll` required by `_ctypes.pyd`, instead of copying the whole Conda environment.

After building, both scripts validate the ordinary PE import tables of all DLLs and Python native extensions, including transitive dependencies. Missing non-system DLLs cause a failed exit status before the success message. The single-file check reads the EXE archive directly and cannot borrow libraries from the developer's PATH.

If dependencies are missing, the scripts install the project requirements and PyInstaller automatically. Without an existing virtual environment, only a system installation of 64-bit Python 3.10 or newer is required. The first dependency installation requires access to a Python package index.

### One-Click Build

No environment activation is required by default. Run either script to create and reuse the lightweight build environment automatically.

To choose the Python interpreter used to create that environment:

```powershell
$env:OCRA_BUILD_PYTHON = "D:\miniconda3\envs\Python3.13\python.exe"
```

To temporarily use the currently active Conda or standard virtual environment instead:

```powershell
$env:OCRA_USE_ACTIVE_ENV = "1"
```

Build the folder distribution:

```powershell
.\py_build\build_exe.bat
```

Build the single-file distribution:

```powershell
.\py_build\build_single_exe.bat
```

Run the scripts from a terminal in the project directory to retain the complete build log. They validate the Python version, 64-bit architecture, build dependencies, and required files, then run the shared build entry point with the selected interpreter to invoke PyInstaller.

The build outputs are located at:

```text
py_build\dist\OCRA\OCRA.exe
py_build\dist_single\OCRA_Single.exe
```

When distributing the application, copy the entire directory:

```text
py_build\dist\OCRA\
```

For the single-file distribution, provide `py_build/dist_single/config` with `OCRA_Single.exe` to retain the project's default configuration. Do not copy only `OCRA.exe` from the folder distribution, because PyQt6, OpenCV, the Python runtime, and camera DLLs are stored in the same application directory.

### Cross-Machine Release Checks

Rebuild before replacing release assets. Editing the scripts does not repair an existing EXE. Target computers do not need Python or Conda installed.

To recheck existing outputs from the project directory:

```powershell
.\py_build\.build_env\Scripts\python.exe .\py_build\build_runtime.py verify .\py_build\dist\OCRA
.\py_build\.build_env\Scripts\python.exe .\py_build\build_runtime.py verify .\py_build\dist_single\OCRA_Single.exe
```

The automated check validates ordinary imported file dependencies only. It does not replace compatibility tests for the target Windows version, CPU, delay-loaded components, or real camera drivers. Before releasing, launch both variants and test camera functionality on a clean Windows 10/11 x64 system without Python or Conda installed.

---

## Frequently Asked Questions

### Why does the outer circle need to be snapped three times?

The three clicks independently sample three fixed video frames After the third pass is completed, the program checks the consistency of the three passes and combines all valid edge inliers, reducing the influence of single-frame noise, reflections, occlusion, or occasional incorrect edges on the final center

### Does clicking the image record circumference points?

No The mouse is only used to move the initial search position or pan the zoomed image It does not participate in three-point circle determination and does not clear the `1/3` or `2/3` progress

### Why does the program display “Insufficient angular coverage” or “Ill-conditioned fitting matrix”?

This indicates that the valid edge points are concentrated on an excessively short arc Even if the local residual is small, the center cannot be determined stably under this geometric condition Adjust the outer-circle position, radius, exposure, or edge-band width so that the program can detect a more complete circumference of the telescope tube

### Why do exposure, ISO, or focus controls not respond for a USB camera?

OpenCV/UVC controls depend on the specific camera and driver Some devices do not support certain parameters, or the parameter scale may not correspond directly to the interface value The program attempts to write the values and safely ignores unsupported controls

### Why can the ZWO camera not be found?

Check the following:

- The official ZWO driver is installed
- A 64-bit Python interpreter or 64-bit EXE is used
- `ASICamera2.dll` is a compatible 64-bit SDK DLL
- The camera is not occupied by another program
- The USB data cable and power supply are working properly

### What should I do if the software still drops frames after running zoomed in for some time?

Recommended:

- Set `ui_fps_limit` to 10–20 FPS
- Reduce the camera resolution
- Reduce the display-window size or zoom ratio
- Disable unnecessary continuous-snapping targets
- Check whether the exposure time is already longer than the target frame interval

---

## Development Notes

The project separates the camera layer, state layer, vision-algorithm layer, and UI layer:

- When adding a camera backend, implement the `BaseCamera` interface and register it in `cameras/factory.py`
- Configuration fields are defined centrally in `core/app_state.py`
- Chinese and English interface text is maintained centrally in `core/i18n.py`
- Circle fitting, HUD, and overlay logic are located in `core/vision_engine.py`
- Main-window interaction and the three-pass outer-edge snapping state machine are located in `ui/main_window.py`

The QHY backend is currently a placeholder implementation Contributions based on the QHYCCD SDK for device enumeration, parameter control, and video capture are welcome

---

## Accuracy and Usage Limitations

- OCRA is a collimation assistance tool The final result is still affected by lens distortion, camera mounting tilt, mechanical eccentricity, non-circular telescope tube edges, reflections, and focus conditions
- A small fitting residual does not necessarily mean that the actual mechanical axis is completely accurate It is recommended to verify the result by rotating the camera and repeating the test, as well as by performing an actual star test
- With clear edges and sufficient circumferential coverage, the algorithm can achieve subpixel repeatability Actual mechanical absolute error also depends on optical and mounting conditions
- Condition-number and angular-coverage checks reject clearly degenerate short-arc results, preventing the output of a center that appears normal but is actually unreliable

---

## License

OCRA's original source code is released under the **Mozilla Public License 2.0 (MPL-2.0)** You may use, modify, and distribute this project, but when distributing modifications to MPL-covered files, you must continue to provide the corresponding source code and retain the license notice See [`LICENSE`](./LICENSE) for the complete terms

`ASICamera2.dll`, camera SDKs, Python dependencies, and other third-party components are not part of OCRA's original source code and are not automatically covered by MPL-2.0 They are governed by their respective licenses or distribution terms See [`THIRD_PARTY_NOTICES.md`](./THIRD_PARTY_NOTICES.md) for details

> Before publicly distributing a source package or EXE containing `ASICamera2.dll`, confirm that the current ZWO SDK terms permit your intended distribution method If this cannot be confirmed, do not include the DLL in the repository and require users to obtain it directly from the official SDK
