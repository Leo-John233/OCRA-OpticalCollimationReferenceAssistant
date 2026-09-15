# Code conventions and design rules

- Use 4-space Python, snake_case functions/methods, PascalCase classes, uppercase module constants, and leading underscore for internal helpers.
- Add return/parameter annotations. Existing code mixes modern built-ins (`list[T]`, `A | None`) with `typing.Optional/Tuple/Dict`; match the touched module.
- Use dataclasses for shared state and structured diagnostic results. Avoid mutable dataclass defaults; initialize nested objects in `__post_init__` or use factories.
- Public classes/functions use concise Chinese docstrings/comments; UI strings must be keys in `core/i18n.py`, not duplicated literals.
- Color tuples are OpenCV BGR, not RGB. Frames crossing camera/video/vision/UI layers are NumPy BGR arrays.
- Register camera types only in `cameras/factory.py`; UI and video thread must depend on `BaseCamera`, not brand SDK details.
- Define persistent config fields/defaults in `core/app_state.py`; serialize through `ConfigManager` and `config/config.txt`.
- Hardware/driver operations should fail safely, release resources in `close`, and surface status instead of crashing the UI.
- Preserve Qt override names (`eventFilter`, `closeEvent`, mouse event methods); local `# noqa` markers document intentional naming/untyped Qt signatures.
- Preserve single-frame backpressure in `VideoThread`; do not queue unbounded frames.
- Keep source/frozen resource lookup and Windows DLL/Qt plugin setup compatible.