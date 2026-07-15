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
├─ build_exe.bat                   # One-click Windows EXE build script
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
- PyQt6 6.6 or later
- OpenCV 4.8 or later
- NumPy 1.24 or later
- Pillow 10.0 or later

Using a ZWO ASI camera also requires:

- Properly installed ZWO camera drivers
- A 64-bit `ASICamera2.dll`
- The camera is not exclusively occupied by ASIStudio, SharpCap, or another program

> Model-specific or DirectShow DLLs such as `ASI662MM-Pro.dll` and `ASI120MM.dll` are not SDK entry points OCRA requires the SDK DLL named `ASICamera2.dll`

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

The project provides `build_exe.bat`, which uses PyInstaller's `onedir` mode to build the Windows application

### One-Click Build

Double-click:

```text
build_exe.bat
```

Or run it in CMD from the project directory:

```bat
build_exe.bat
```

The script automatically:

1. Checks for 64-bit Python 3.13, 3.12, or the default Python
2. Creates or reuses `.venv`
3. Installs project dependencies and PyInstaller
4. Cleans the old `build` and `dist` directories
5. Packages `config` and the optional `ASICamera2.dll`
6. Generates an application without a console window

The build output is located at:

```text
dist\OCRA\OCRA.exe
```

When distributing the application, copy the entire directory:

```text
dist\OCRA\
```

Do not copy only `OCRA.exe`, because PyQt6, OpenCV, the Python Runtime, configuration files, camera DLLs, and other runtime files are located in the same application directory

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
