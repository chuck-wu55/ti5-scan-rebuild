from __future__ import annotations

import json
from pathlib import Path
from typing import Any

SW_IMPORT_STL_VRML_MODEL_TYPE = 208
SW_IMPORT_STL_VRML_UNITS = 210
SW_IMPORT_UNIT_PREFERENCE = 205
SW_IMPORT_STL_VRML_TEXTURE_INFORMATION = 303
SW_VRML_STL_IMPORT_AS_PS_MESH = 679
SW_VRML_STL_IMPORT_SEGMENTED = 682
SW_IMPORT_SOLID_BODY = 2
SW_BODY_TYPE_SOLID = 0
SW_LENGTH_UNITS = {"mm": 0, "cm": 1, "m": 2, "inch": 3}


def _member(obj: Any, name: str) -> Any:
    value = getattr(obj, name)
    return value() if callable(value) else value


def probe_solidworks() -> tuple[bool, str]:
    """Only attach to an existing instance; a health check must not launch CAD."""
    try:
        import pythoncom
        import win32com.client
        pythoncom.CoInitialize()
        try:
            app = win32com.client.GetActiveObject("SldWorks.Application")
            return True, f"SolidWorks {_member(app, 'RevisionNumber')} 已连接"
        finally:
            pythoncom.CoUninitialize()
    except Exception:
        return False, "SolidWorks 未连接，请先启动 SolidWorks"


def _body_count(model: Any) -> int:
    try:
        bodies = model.GetBodies2(SW_BODY_TYPE_SOLID, True)
    except Exception:
        bodies = None
    if bodies is None:
        return 0
    return len(bodies) if isinstance(bodies, (tuple, list)) else 1


def _save_views(model: Any, review_dir: Path, basename: str) -> list[str]:
    review_dir.mkdir(parents=True, exist_ok=True)
    previews: list[str] = []
    for name, view_id in (("front", 1), ("right", 4), ("top", 5), ("isometric", 7)):
        path = review_dir / f"{basename}_{name}.bmp"
        try:
            model.ShowNamedView2("*", view_id)
            model.ViewZoomtofit2()
            model.GraphicsRedraw2()
            if bool(model.SaveBMP(str(path), 1280, 960)) and path.is_file():
                previews.append(str(path))
        except Exception:
            continue
    return previews


def import_editable_solid(source: Path, output: Path, review_dir: Path, units: str = "mm") -> dict[str, Any]:
    """Import a closed STL as a verified SolidWorks solid body.

    The resulting imported body supports direct editing and downstream features.
    It does not claim to reconstruct the scan's original design history.
    """
    unit_key = units.strip().lower()
    if unit_key not in SW_LENGTH_UNITS:
        raise ValueError(f"不支持的 STL 单位：{units}")
    if not source.is_file():
        raise FileNotFoundError(str(source))

    import pythoncom
    import win32com.client
    from win32com.client import VARIANT

    pythoncom.CoInitialize()
    try:
        try:
            sw = win32com.client.GetActiveObject("SldWorks.Application")
        except Exception as exc:
            raise RuntimeError("未连接到 SolidWorks。请先启动 SolidWorks，等待主界面完成加载后重试。") from exc
        sw.Visible = True
        operations = []
        for preference, value in (
            (SW_IMPORT_STL_VRML_MODEL_TYPE, SW_IMPORT_SOLID_BODY),
            (SW_IMPORT_STL_VRML_UNITS, SW_LENGTH_UNITS[unit_key]),
            (SW_IMPORT_UNIT_PREFERENCE, 0),
        ):
            ok = sw.SetUserPreferenceIntegerValue(preference, value)
            operations.append({"preference": preference, "value": value, "ok": bool(ok)})
        for preference, value in (
            (SW_IMPORT_STL_VRML_TEXTURE_INFORMATION, False),
            (SW_VRML_STL_IMPORT_AS_PS_MESH, False),
            (SW_VRML_STL_IMPORT_SEGMENTED, False),
        ):
            sw.SetUserPreferenceToggle(preference, value)

        errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        model = sw.LoadFile4(str(source), "r", VARIANT(pythoncom.VT_DISPATCH, None), errors)
        if model is None:
            raise RuntimeError(
                f"SolidWorks 无法把该 STL 导入为实体，LoadFile4 错误码 {errors.value}。"
                "请检查网格是否闭合、自交或面数过高，并确认单位设置。"
            )
        model.ClearSelection2(True)
        model.ForceRebuild3(False)
        body_count = _body_count(model)
        if body_count < 1:
            raise RuntimeError(
                "SolidWorks 已打开 STL，但没有生成实体 Body。该网格可能不闭合或过于复杂；"
                "本软件不会把图形网格冒充可编辑实体。"
            )

        output.parent.mkdir(parents=True, exist_ok=True)
        save_errors = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        save_warnings = VARIANT(pythoncom.VT_BYREF | pythoncom.VT_I4, 0)
        saved = model.Extension.SaveAs(
            str(output), 0, 1, VARIANT(pythoncom.VT_DISPATCH, None), save_errors, save_warnings
        )
        if not saved or not output.is_file() or output.stat().st_size == 0:
            raise RuntimeError(f"SolidWorks 实体保存失败，错误码 {save_errors.value}，警告码 {save_warnings.value}")

        previews = _save_views(model, review_dir, output.stem)
        result = {
            "status": "passed", "source": str(source), "output_sldprt": str(output),
            "output_size_bytes": output.stat().st_size,
            "solidworks_revision": str(_member(sw, "RevisionNumber")), "units": unit_key,
            "model_type": "solid", "solid_body_count": body_count,
            "editable_scope": "实体可直接编辑并可继续添加特征；不承诺恢复原始设计历史",
            "preferences": operations, "review_previews": previews,
        }
        review_dir.mkdir(parents=True, exist_ok=True)
        (review_dir / "solid_review.json").write_text(json.dumps(result, ensure_ascii=False, indent=2), encoding="utf-8")
        return result
    finally:
        pythoncom.CoUninitialize()


def import_reference(source: Path, output: Path, review_dir: Path, units: str = "mm") -> dict[str, Any]:
    """Backward-compatible entry point that now requires a verified solid body."""
    return import_editable_solid(source, output, review_dir, units)
