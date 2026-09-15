# UI module

- `MainWindow` owns controls, localization application, camera lifecycle, parameter persistence, image display, tracking orchestration, and the three-pass outer-snap state machine.
- `VideoThread` owns capture and control application. It uses single-frame backpressure: emit only when the prior frame was consumed; preserve this invariant.
- `InteractiveVideoLabel` maps mouse/wheel coordinates between displayed/cropped frames and original camera coordinates. Zoom/pan are display transformations; detection remains in original frame coordinates.
- Mouse clicks move the next search seed; they are not circle sample points and must not reset completed outer-snap rounds.
- After locking the outer reference center, geometry-changing outer controls remain disabled until reset; cosmetic color/width controls may remain editable.
- Circle continuous tracking is disabled when that circle is configured concentric with the outer reference.
- Camera-control edits are debounced to avoid frequent SDK calls.
- `EnvironmentCheckDialog` renders/copies `EnvironmentReport`; startup failures before Qt use native fallback handling in core.
- Qt callback names intentionally follow Qt APIs even when they violate snake_case.
- Read state/vision invariants in `mem:core_module/core` and camera contracts in `mem:cameras/core`.