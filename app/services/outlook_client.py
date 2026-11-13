"""메일함 읽기 — 서버 PC 클래식 Outlook(COM)의 정해진 폴더(M13, F22).

**dcost `modules/outlook_client.py` 2026-10-23 스냅숏에서 필요한 부분만** 들여왔다(정본은 자기 repo 안에 — 남의 폴더를 가리키지 않는다).
가져온 것: available · running(가벼운 판) · _namespace · _folder · _walk · _attachments(숨김·인라인 이미지·클라우드 링크 거름) · _uninit.
뺀 것: 전표 판정·발신처 규칙·제외 기억·본문 표식 — 이 앱은 폴더에 **전달한 메일 전부**를 가져오기 후보로 본다.

- pywin32·Outlook 이 없거나 COM 이 실패하면 **None** 을 돌려준다(가져오기 화면의 메일함 입구가 휴면 안내를 띄운다).
- 호출마다 `pythoncom.CoInitialize()` — 웹 서버 스레드에서 부르기 때문(dcost 와 같은 이유).
- **발신자·수신자는 읽지 않는다**(개인정보 최소수집). 제목·받은 때·본문 HTML·첨부만.
- 주기 수집은 아직 없다 — 화면의 「메일함에서 가져오기」 버튼으로만 읽는다(2026-10-23 사용자 결정).
"""
from __future__ import annotations

import os
import tempfile
from datetime import datetime, timedelta
from pathlib import Path

PR_MESSAGE_ID = "http://schemas.microsoft.com/mapi/proptag/0x1035001F"
PR_HIDDEN = "http://schemas.microsoft.com/mapi/proptag/0x7FFE000B"
PR_CONTENT_ID = "http://schemas.microsoft.com/mapi/proptag/0x3712001F"
_IMG = (".png", ".jpg", ".jpeg", ".gif", ".bmp")

LAST_ERRORS: list[str] = []


def available() -> bool:
    if os.environ.get("MEETING_NO_OUTLOOK"):          # 회귀(_smoke)에서 켜진 Outlook 에 붙지 않게
        return False
    try:
        import pythoncom  # noqa: F401
        import win32com.client  # noqa: F401
        return True
    except Exception:  # noqa: BLE001 — pywin32 없음(비 Windows·미설치) → 휴면
        return False


def why_not(folder: str) -> str:
    """메일함 입구가 쉬는 이유 — 화면 안내용. 쓸 수 있으면 ''."""
    if not folder:
        return "메일 폴더가 정해지지 않았습니다 — secret/.env 에 MEETING_MAIL_FOLDER(받은편지함 아래 경로)를 넣어주세요."
    if not available():
        return "이 PC 에서 Outlook 을 읽을 수 없습니다(pywin32 없음) — 서버 PC 에서 setup_env.bat 을 다시 실행해주세요."
    return ""


def _namespace():
    import pythoncom
    import win32com.client

    pythoncom.CoInitialize()
    try:
        app = win32com.client.GetActiveObject("Outlook.Application")
    except Exception:  # noqa: BLE001 — 실행 중 아님 → 새로 띄운다
        app = win32com.client.Dispatch("Outlook.Application")
    return app.GetNamespace("MAPI")


def _folder(ns, path: str):
    inbox = ns.GetDefaultFolder(6)   # olFolderInbox
    parts = [p for p in (path or "").replace("\\", "/").split("/") if p]
    if parts and parts[0] == inbox.Name:
        parts = parts[1:]
    f = inbox
    for p in parts:
        f = f.Folders[p]
    return f


def _walk(f, path: str, depth: int, out: list) -> None:
    out.append((path, f))
    if depth <= 0:
        return
    try:
        subs = list(f.Folders)
    except Exception:  # noqa: BLE001 — 하위 폴더 열람 실패 → 그 폴더만
        return
    for sub in subs:
        try:
            if int(sub.DefaultItemType) != 0:     # 메일 폴더만
                continue
            name = sub.Name
        except Exception:  # noqa: BLE001 — 속성 불가 → 건너뜀
            continue
        _walk(sub, f"{path}/{name}", depth - 1, out)


def _uninit():
    try:
        import pythoncom
        pythoncom.CoUninitialize()
    except Exception:  # noqa: BLE001 — 초기화 안 된 스레드 → 무해
        pass


def _attachments(item, tmpdir: str) -> list[tuple[str, bytes]]:
    """첨부를 (이름, 바이트)로. 숨김·본문 인라인 이미지(로고·서명)·클라우드 링크·OLE 개체는 뺀다."""
    out = []
    try:
        n = item.Attachments.Count
    except Exception as e:  # noqa: BLE001 — 첨부 목록을 못 읽음
        LAST_ERRORS.append(f"첨부 목록: {type(e).__name__}")
        return out
    for i in range(1, n + 1):
        name = f"첨부{i}"
        try:
            a = item.Attachments.Item(i)
            try:
                typ = int(a.Type)
            except Exception:  # noqa: BLE001 — Type 없음 → 파일로 본다
                typ = 1
            name = a.FileName or f"첨부{i}"
            if typ in (4, 6):                               # 클라우드 링크 · OLE 개체 — 파일로 저장 불가
                LAST_ERRORS.append(f"첨부 「{name}」 — 링크·개체 첨부라 가져오지 못함(파일로 받아 다시 전달해주세요)")
                continue
            pa = a.PropertyAccessor
            try:
                if pa.GetProperty(PR_HIDDEN):
                    continue
            except Exception:  # noqa: BLE001 — 속성 없음 = 숨김 아님
                pass
            try:
                cid = pa.GetProperty(PR_CONTENT_ID)
            except Exception:  # noqa: BLE001
                cid = ""
            if cid and name.lower().endswith(_IMG):
                continue
            p = Path(tmpdir) / f"{i}_{os.getpid()}"
            a.SaveAsFile(str(p))
            out.append((name, p.read_bytes()))
            p.unlink(missing_ok=True)
        except Exception as e:  # noqa: BLE001 — 첨부 하나 실패해도 메일은 계속
            LAST_ERRORS.append(f"첨부 「{name}」: {type(e).__name__}")
    return out


def fetch(folder: str, days: int, known: set[str], limit: int = 200) -> list[dict] | None:
    """폴더(+하위)의 최근 days 일 메일. known(이미 가져온 Message-ID·EntryID)은 첨부를 꺼내지 않고 뺀다. Outlook 불가면 None."""
    LAST_ERRORS.clear()
    if not available():
        LAST_ERRORS.append("pywin32 미설치")
        return None
    since = (datetime.now() - timedelta(days=max(1, days))).strftime("%m/%d/%Y %H:%M")
    out: list[dict] = []
    try:
        ns = _namespace()
        base = _folder(ns, folder)
        folders: list = []
        _walk(base, base.Name, 3, folders)
        seen: set = set()
        with tempfile.TemporaryDirectory(prefix="meeting_mail_") as tmp:
            for path, f in folders:
                try:
                    res = f.Items.Restrict(f"[ReceivedTime] >= '{since}'")
                    res.Sort("[ReceivedTime]", True)
                except Exception as e:  # noqa: BLE001 — 폴더 하나 실패해도 계속
                    LAST_ERRORS.append(f"폴더 {path}: {type(e).__name__}")
                    continue
                for it in res:
                    if len(out) >= limit:
                        break
                    try:
                        if it.Class != 43:                       # 메일만
                            continue
                        eid = it.EntryID
                        try:
                            mid = it.PropertyAccessor.GetProperty(PR_MESSAGE_ID) or ""
                        except Exception:  # noqa: BLE001 — 속성 없음 → EntryID 로
                            mid = ""
                        key = mid or eid
                        if key in seen or key in known or eid in known:
                            continue
                        seen.add(key)
                        out.append({"message_id": mid, "entry_id": eid, "subject": it.Subject or "",
                                    "received_at": it.ReceivedTime.strftime("%Y-%m-%d %H:%M"), "html": it.HTMLBody or "",
                                    "attachments": _attachments(it, tmp), "folder": path})
                    except Exception as e:  # noqa: BLE001 — 메일 한 통 실패해도 계속
                        LAST_ERRORS.append(f"메일: {type(e).__name__}")
        return out
    except Exception as e:  # noqa: BLE001 — Outlook 미실행·프로필 없음·폴더 없음 → None
        LAST_ERRORS.append(f"Outlook: {type(e).__name__}: {str(e)[:160]}")
        return None
    finally:
        _uninit()
