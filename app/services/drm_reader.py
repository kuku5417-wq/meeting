"""DRM 엑셀 읽기 — 문서 보안이 걸린 .xlsx 를 서버 PC 의 Excel(COM)로 열어 시트 값을 읽는다 (2026-10-29).

dcost/drm_reader.py(2026-10-29 시점) 스냅샷을 meeting 에 맞게 고친 것(정본은 자기 repo 안에 둔다).
- 바뀐 점: 평문 xlsx bytes 로 다시 만들지 않고 **시트별 행 값**을 바로 돌려준다(openpyxl 의존성을 들이지 않으려고).
  costplan 의 `last_error()` 접근자를 함께 둔다(KNOWN_ISSUES #13).
- 지키는 것: COM 초기화(웹 요청은 워커 스레드), DispatchEx 우선·실패 시 열린 Excel 에 붙되 그땐 Quit 금지,
  ReadOnly 로 열고 저장 없이 닫기, A1 고정 범위.
- 숨긴 시트·차트 시트는 건너뛴다(평문 엑셀 가져오기와 같다).
- Excel·pywin32 가 없거나(사외 PC) 문서 권한이 없으면 None — 사유는 `last_error()`. 앱은 그대로 돈다.
"""
from __future__ import annotations

import gc
import logging
import os
import tempfile

_LAST_ERR = ""
_XL_VISIBLE = -1          # xlSheetVisible


def last_error() -> str:
    return _LAST_ERR


def _read(win32, path: str) -> list[tuple[str, list[list]]]:
    """Excel 을 띄워 읽고 닫는다. COM 참조는 이 함수의 지역 변수뿐 — 돌아오면 모두 놓인다
    (참조를 쥔 채 CoUninitialize 하면 Quit 한 Excel 이 프로세스로 남는다)."""
    own_instance = False
    excel_app = wb = None
    try:
        try:
            excel_app = win32.DispatchEx("Excel.Application")
            own_instance = True                       # 우리가 띄운 인스턴스만 Quit
        except Exception:  # noqa: BLE001 — 새 인스턴스 실패 → 열린 Excel 에 붙는다(Quit 하면 편집 중 문서가 닫힌다)
            excel_app = win32.Dispatch("Excel.Application")
        excel_app.Visible = False
        excel_app.DisplayAlerts = False
        excel_app.AskToUpdateLinks = False
        # Password="" — 암호 걸린 파일이면 묻는 창 대신 오류로 끝난다(서버에서 창이 뜨면 요청이 멈춘다)
        wb = excel_app.Workbooks.Open(path, UpdateLinks=0, ReadOnly=True, Password="")
        out = []
        for sheet in wb.Worksheets:
            if sheet.Visible != _XL_VISIBLE:
                continue
            used = sheet.UsedRange
            last_row = used.Row + used.Rows.Count - 1
            last_col = used.Column + used.Columns.Count - 1
            values = sheet.Range(sheet.Cells(1, 1), sheet.Cells(last_row, last_col)).Value   # A1 고정
            if values is None:
                rows = []
            elif not isinstance(values, (list, tuple)):
                rows = [[values]]
            else:
                rows = [list(r) if isinstance(r, (list, tuple)) else [r] for r in values]
            out.append((str(sheet.Name), rows))
        return out
    finally:
        if wb is not None:
            try:
                wb.Close(SaveChanges=False)
            except Exception:  # noqa: BLE001 — 닫기 실패 → 인스턴스 정리로 넘어간다
                pass
        if excel_app is not None and own_instance:
            try:
                excel_app.Quit()
            except Exception:  # noqa: BLE001 — 이미 끝난 인스턴스
                pass


def read_sheets(data: bytes, suffix: str = ".xlsx") -> list[tuple[str, list[list]]] | None:
    """엑셀 bytes → [(시트 이름, [[칸 값…]…])]. 값은 COM 이 준 그대로(str·float·bool·날짜·None). 실패 시 None."""
    global _LAST_ERR
    _LAST_ERR = ""
    co_init = False
    fd, tmp = tempfile.mkstemp(suffix=suffix, prefix="meeting_drm_")   # COM 은 경로로만 연다
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        try:
            import win32com.client as win32          # 지연 import — 없으면 휴면
        except ImportError:
            _LAST_ERR = "이 PC 에 pywin32 가 없습니다"
            return None
        try:
            import pythoncom
            pythoncom.CoInitialize()
            co_init = True
        except Exception:  # noqa: BLE001 — 이미 초기화된 스레드 → 그대로 진행
            pass
        return _read(win32, os.path.abspath(tmp))
    except Exception as e:  # noqa: BLE001 — Excel 미설치·문서 권한 없음·암호 → None + 사유
        logging.warning("DRM 엑셀 읽기 실패: %s: %s", type(e).__name__, e)
        info = getattr(e, "excepinfo", None) or (e.args[2] if len(e.args) > 2 and isinstance(e.args[2], tuple) else None)
        msg = info[2] if info and len(info) > 2 and info[2] else f"{type(e).__name__}: {e}"   # Excel 이 준 설명만 보인다
        _LAST_ERR = msg.replace(os.path.basename(tmp), "올린 파일")[:300]
        return None
    finally:
        if co_init:
            gc.collect()                              # 오류 추적에 남은 COM 참조까지 놓은 뒤 정리
            try:
                import pythoncom
                pythoncom.CoUninitialize()
            except Exception:  # noqa: BLE001 — 정리 실패는 무시
                pass
        try:
            os.remove(tmp)
        except OSError:  # Excel 이 아직 잡고 있으면 임시 폴더에 남는다
            pass
