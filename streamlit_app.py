"""쇼핑 리스트 — Streamlit 버전 (PRD.md 기준).

실행: python -m streamlit run streamlit_app.py

웹 버전(index.html)은 브라우저 localStorage에 저장하지만, Streamlit은 서버에서 동작하므로
같은 폴더의 shopping_list.json 파일에 저장한다. 데이터 구조는 PRD 4장 Item과 같다.
"""

from __future__ import annotations

import json
import math
import os
import tempfile
import time
import uuid
from pathlib import Path

import streamlit as st

DATA_FILE = Path(__file__).with_name("shopping_list.json")
NAME_MAX = 50
MEMO_MAX = 100
QTY_MAX = 999
PRICE_MAX = 100_000_000

FILTERS = ["전체", "미완료", "완료"]

st.set_page_config(page_title="쇼핑 리스트", page_icon="🛒", layout="wide")


# ---------------------------------------------------------------------------
# 저장소
# ---------------------------------------------------------------------------

def _is_number(value) -> bool:
    return isinstance(value, (int, float)) and not isinstance(value, bool)


def _is_valid_item(value) -> bool:
    return (
        isinstance(value, dict)
        and isinstance(value.get("id"), str)
        and isinstance(value.get("name"), str)
        and value["name"].strip() != ""
        and isinstance(value.get("quantity"), int)
        and not isinstance(value.get("quantity"), bool)
        and value["quantity"] >= 1
        and (
            value.get("price") is None
            or (_is_number(value["price"]) and math.isfinite(value["price"]) and value["price"] >= 0)
        )
    )


def load_items() -> list[dict]:
    """파일에서 아이템을 읽는다. 없거나 손상되면 빈 리스트."""
    try:
        data = json.loads(DATA_FILE.read_text(encoding="utf-8"))
    except (OSError, ValueError):
        return []
    if not isinstance(data, list):
        return []
    now = int(time.time() * 1000)
    return [
        {
            "id": item["id"],
            "name": item["name"][:NAME_MAX],
            "quantity": item["quantity"],
            "price": item["price"],
            "memo": item["memo"][:MEMO_MAX] if isinstance(item.get("memo"), str) else "",
            "checked": item.get("checked") is True,
            "inCart": item.get("inCart") is True,
            "createdAt": item.get("createdAt") if _is_number(item.get("createdAt")) else now,
            "updatedAt": item.get("updatedAt") if _is_number(item.get("updatedAt")) else now,
        }
        for item in data
        if _is_valid_item(item)
    ]


def save_items(items: list[dict]) -> None:
    """임시 파일에 쓴 뒤 교체해 저장 도중 파일이 깨지지 않게 한다."""
    try:
        fd, tmp = tempfile.mkstemp(dir=DATA_FILE.parent, prefix=".shopping_list.", suffix=".tmp")
        with os.fdopen(fd, "w", encoding="utf-8") as f:
            json.dump(items, f, ensure_ascii=False, indent=2)
        os.replace(tmp, DATA_FILE)
    except OSError:
        notify("저장하지 못했어요. 폴더 권한을 확인해 주세요.", "⚠️")


def mutate(change) -> None:
    """모든 상태 변경의 공통 흐름: 파일에서 최신 상태 읽기 → 변경 → 저장.

    매번 파일에서 다시 읽기 때문에 여러 탭에서 동시에 써도 서로 덮어쓰지 않는다.
    """
    items = load_items()
    change(items)
    save_items(items)


def find(items: list[dict], item_id: str) -> dict | None:
    return next((item for item in items if item["id"] == item_id), None)


def now_ms() -> int:
    return int(time.time() * 1000)


# ---------------------------------------------------------------------------
# 유틸
# ---------------------------------------------------------------------------

def format_won(amount: float) -> str:
    if isinstance(amount, float) and amount.is_integer():
        amount = int(amount)
    return f"{amount:,}원"


def price_text(price) -> str:
    return "가격 미입력" if price is None else format_won(price)


_MD_SPECIAL = set("\\`*_{}[]()#+-.!|~<>$:")


def md_escape(text: str) -> str:
    """사용자 입력을 마크다운 서식 없이 글자 그대로 보이게 한다."""
    return "".join(f"\\{ch}" if ch in _MD_SPECIAL else ch for ch in text)


def validate(name, quantity, price, memo) -> tuple[dict | None, str | None]:
    name = (name or "").strip()
    if not name:
        return None, "아이템 이름을 입력해 주세요."
    if len(name) > NAME_MAX:
        return None, f"이름은 {NAME_MAX}자 이하로 입력해 주세요."
    if quantity is None or int(quantity) != quantity or not 1 <= quantity <= QTY_MAX:
        return None, f"수량은 1~{QTY_MAX} 사이의 정수로 입력해 주세요."
    if price is not None and not 0 <= price <= PRICE_MAX:
        return None, f"단가는 0~{PRICE_MAX:,}원 사이로 입력해 주세요."
    memo = (memo or "").strip()
    if len(memo) > MEMO_MAX:
        return None, f"메모는 {MEMO_MAX}자 이하로 입력해 주세요."
    return {"name": name, "quantity": int(quantity), "price": None if price is None else int(price), "memo": memo}, None


def notify(message: str, icon: str = "✅") -> None:
    """콜백 안에서도 쓸 수 있도록 큐에 넣고, 본문에서 st.toast로 띄운다."""
    st.session_state.setdefault("toasts", []).append((message, icon))


# ---------------------------------------------------------------------------
# 세션 상태 기본값
# ---------------------------------------------------------------------------

ss = st.session_state
ss.setdefault("editing_id", None)
ss.setdefault("edit_error", None)
ss.setdefault("add_error", None)
ss.setdefault("last_deleted", [])  # [(item, index), ...] — 실행 취소용
ss.setdefault("deleted_message", "")
ss.setdefault("add_name", "")
ss.setdefault("add_qty", 1)
ss.setdefault("add_price", None)
ss.setdefault("add_memo", "")
ss.setdefault("filter", "전체")


# ---------------------------------------------------------------------------
# 상태 변경 (위젯 콜백)
# ---------------------------------------------------------------------------

def add_item() -> None:
    fields, error = validate(ss.add_name, ss.add_qty, ss.add_price, ss.add_memo)
    if error:
        ss.add_error = error
        return
    ss.add_error = None

    def change(items):
        ts = now_ms()
        items.insert(0, {"id": str(uuid.uuid4()), **fields, "checked": False, "inCart": False,
                         "createdAt": ts, "updatedAt": ts})

    mutate(change)
    ss.add_name, ss.add_qty, ss.add_price, ss.add_memo = "", 1, None, ""


def update(item_id: str, **changes) -> None:
    def change(items):
        item = find(items, item_id)
        if item:
            item.update(changes, updatedAt=now_ms())

    mutate(change)


def toggle_checked(item_id: str) -> None:
    item = find(load_items(), item_id)
    if item:
        update(item_id, checked=not item["checked"])


def toggle_cart(item_id: str) -> None:
    item = find(load_items(), item_id)
    if item:
        update(item_id, inCart=not item["inCart"])


def change_quantity(item_id: str, delta: int) -> None:
    item = find(load_items(), item_id)
    if item and 1 <= item["quantity"] + delta <= QTY_MAX:
        update(item_id, quantity=item["quantity"] + delta)


def start_edit(item_id: str) -> None:
    item = find(load_items(), item_id)
    if not item:
        return
    ss.editing_id = item_id
    ss.edit_error = None
    ss.edit_name = item["name"]
    ss.edit_qty = item["quantity"]
    ss.edit_price = None if item["price"] is None else int(item["price"])
    ss.edit_memo = item["memo"]


def cancel_edit() -> None:
    ss.editing_id = None
    ss.edit_error = None


def save_edit() -> None:
    fields, error = validate(ss.edit_name, ss.edit_qty, ss.edit_price, ss.edit_memo)
    if error:
        ss.edit_error = error
        return
    update(ss.editing_id, **fields)
    cancel_edit()


def remember_deleted(entries: list[tuple[dict, int]], message: str) -> None:
    ss.last_deleted = entries
    ss.deleted_message = message


def delete_item(item_id: str) -> None:
    def change(items):
        index = next((i for i, item in enumerate(items) if item["id"] == item_id), None)
        if index is None:
            return
        removed = items.pop(index)
        remember_deleted([(removed, index)], f"“{removed['name']}”을(를) 삭제했어요.")

    mutate(change)
    if ss.editing_id == item_id:
        cancel_edit()


def clear_checked() -> None:
    def change(items):
        removed = [(item, i) for i, item in enumerate(items) if item["checked"]]
        if not removed:
            return
        items[:] = [item for item in items if not item["checked"]]
        remember_deleted(removed, f"체크된 항목 {len(removed)}개를 삭제했어요.")
        if any(item["id"] == ss.editing_id for item, _ in removed):
            cancel_edit()

    mutate(change)


def clear_cart() -> None:
    def change(items):
        ts = now_ms()
        for item in items:
            if item["inCart"]:
                item["inCart"] = False
                item["updatedAt"] = ts

    mutate(change)


def undo_delete() -> None:
    entries = sorted(ss.last_deleted, key=lambda entry: entry[1])

    def change(items):
        existing = {item["id"] for item in items}
        for item, index in entries:
            if item["id"] not in existing:
                items.insert(min(index, len(items)), item)

    mutate(change)
    dismiss_undo()


def dismiss_undo() -> None:
    ss.last_deleted = []
    ss.deleted_message = ""


# ---------------------------------------------------------------------------
# 확인 창
# ---------------------------------------------------------------------------

@st.dialog("아이템 삭제")
def confirm_delete(item_id: str, name: str) -> None:
    st.write(f"“{md_escape(name)}”을(를) 삭제할까요?")
    left, right = st.columns(2)
    if left.button("삭제", type="primary", width="stretch"):
        delete_item(item_id)
        st.rerun()
    if right.button("취소", width="stretch"):
        st.rerun()


@st.dialog("체크된 항목 삭제")
def confirm_clear_checked(count: int) -> None:
    st.write(f"체크된 항목 {count}개를 삭제할까요?")
    left, right = st.columns(2)
    if left.button("삭제", type="primary", width="stretch"):
        clear_checked()
        st.rerun()
    if right.button("취소", width="stretch"):
        st.rerun()


# ---------------------------------------------------------------------------
# 화면
# ---------------------------------------------------------------------------

st.markdown(
    """
    <style>
      .block-container { padding-top: 2rem; max-width: 1180px; }
      [data-testid="stBaseButton-primary"] p, [data-testid="stBaseButton-secondary"] p,
      [data-testid="stBaseButton-tertiary"] p { white-space: nowrap; }
      .item-meta { color: var(--text-muted, #56635a); font-size: 0.9rem; }
      .cart-total { font-size: 1.8rem; font-weight: 800; color: #15803d; text-align: right; }
      @media (prefers-color-scheme: dark) { .cart-total { color: #4ade80; } }
    </style>
    """,
    unsafe_allow_html=True,
)

items = load_items()
if ss.editing_id and not find(items, ss.editing_id):
    cancel_edit()  # 다른 탭에서 삭제된 아이템

for message, icon in ss.pop("toasts", []):
    st.toast(message, icon=icon)

done_count = sum(item["checked"] for item in items)

# 헤더 + 진행률
title_col, progress_col = st.columns([3, 1], vertical_alignment="bottom")
title_col.title("🛒 쇼핑 리스트")
progress_col.markdown(f"<div style='text-align:right;font-weight:700'>{done_count} / {len(items)} 완료</div>",
                      unsafe_allow_html=True)
st.progress(done_count / len(items) if items else 0.0)

list_col, cart_col = st.columns([2, 1], gap="large")

# ---------------- 왼쪽: 추가 폼 + 목록 ----------------
with list_col:
    with st.form("add_form", border=True):
        c1, c2, c3, c4 = st.columns([3, 1.2, 1.6, 2.4])
        c1.text_input("아이템 이름", key="add_name", max_chars=NAME_MAX, placeholder="예: 우유")
        c2.number_input("수량", key="add_qty", min_value=1, max_value=QTY_MAX, step=1)
        c3.number_input("단가(원)", key="add_price", min_value=0, max_value=PRICE_MAX, step=100, placeholder="선택")
        c4.text_input("메모", key="add_memo", max_chars=MEMO_MAX, placeholder="선택")
        st.form_submit_button("추가", type="primary", on_click=add_item, width="stretch")
    if ss.add_error:
        st.error(ss.add_error)

    # 실행 취소 안내
    if ss.last_deleted:
        msg_col, undo_col, close_col = st.columns([5, 1.4, 0.8], vertical_alignment="center")
        msg_col.info(ss.deleted_message, icon="🗑️")
        undo_col.button("실행 취소", on_click=undo_delete, width="stretch")
        close_col.button("✕", on_click=dismiss_undo, help="닫기", width="stretch")

    choice = st.segmented_control("목록 필터", FILTERS, key="filter", label_visibility="collapsed") or "전체"
    if choice == "미완료":
        shown = [item for item in items if not item["checked"]]
    elif choice == "완료":
        shown = [item for item in items if item["checked"]]
    else:
        shown = items
    # 체크된 아이템은 아래로 (화면 순서 = 키보드 이동 순서)
    shown = sorted(shown, key=lambda item: item["checked"])

    if not shown:
        st.info("아직 아이템이 없어요. 위에서 추가해 보세요." if not items else "이 필터에 해당하는 아이템이 없어요.", icon="🧺")

    for item in shown:
        item_id = item["id"]
        with st.container(border=True):
            if item_id == ss.editing_id:
                with st.form(f"edit_form_{item_id}", border=False):
                    e1, e2, e3, e4 = st.columns([3, 1.2, 1.6, 2.4])
                    e1.text_input("이름", key="edit_name", max_chars=NAME_MAX)
                    e2.number_input("수량", key="edit_qty", min_value=1, max_value=QTY_MAX, step=1)
                    e3.number_input("단가(원)", key="edit_price", min_value=0, max_value=PRICE_MAX, step=100,
                                    placeholder="선택")
                    e4.text_input("메모", key="edit_memo", max_chars=MEMO_MAX)
                    s1, s2, _ = st.columns([1, 1, 4])
                    s1.form_submit_button("저장", type="primary", on_click=save_edit, width="stretch")
                    s2.form_submit_button("취소", on_click=cancel_edit, width="stretch")
                if ss.edit_error:
                    st.error(ss.edit_error)
                continue

            check_col, body_col, actions_col = st.columns([0.5, 5, 3.4], vertical_alignment="center")
            # 체크 상태가 바뀌면 key도 바뀌어 위젯 값이 항상 저장된 값과 일치한다
            check_col.checkbox(
                f"{item['name']} 구매 완료",
                value=item["checked"],
                key=f"chk_{item_id}_{item['checked']}",
                on_change=toggle_checked,
                args=(item_id,),
                label_visibility="collapsed",
            )
            name = md_escape(item["name"])
            meta = f"x{item['quantity']} · {price_text(item['price'])}"
            if item["memo"]:
                meta += f" · 📝 {md_escape(item['memo'])}"
            badge = " :green-badge[🛒 담김]" if item["inCart"] else ""
            if item["checked"]:
                body_col.markdown(f"~~**{name}**~~{badge}  \n:gray[~~{meta}~~]")
            else:
                body_col.markdown(f"**{name}**{badge}  \n:gray[{meta}]")
            # 버튼 3개를 한 줄로 묶어, 폭이 좁으면 버튼 단위로 줄바꿈되게 한다
            with actions_col.container(horizontal=True, horizontal_alignment="right", gap="small"):
                st.button(
                    "빼기" if item["inCart"] else "담기",
                    key=f"cart_{item_id}",
                    on_click=toggle_cart,
                    args=(item_id,),
                    type="secondary" if item["inCart"] else "primary",
                )
                st.button("수정", key=f"edit_{item_id}", on_click=start_edit, args=(item_id,))
                if st.button("삭제", key=f"del_{item_id}"):
                    confirm_delete(item_id, item["name"])

    if st.button("체크된 항목 삭제", disabled=done_count == 0):
        confirm_clear_checked(done_count)

# ---------------- 오른쪽: 장바구니 ----------------
with cart_col:
    with st.container(border=True):
        st.subheader("장바구니")
        cart_items = [item for item in items if item["inCart"]]
        if not cart_items:
            st.caption("🛒 장바구니가 비어 있어요.")

        for item in cart_items:
            item_id = item["id"]
            # 1줄: 이름 + 빼기 / 2줄: 단가 / 3줄: − 수량 + … 소계
            n_col, rm_col = st.columns([3, 1], vertical_alignment="center")
            n_col.markdown(f"**{md_escape(item['name'])}**  \n:gray[{'가격 미입력' if item['price'] is None else '단가 ' + format_won(item['price'])}]")
            rm_col.button("빼기", key=f"rm_{item_id}", on_click=toggle_cart, args=(item_id,), type="tertiary",
                          help=f"{item['name']} 장바구니에서 빼기", width="stretch")
            dec_col, qty_col, inc_col, sub_col = st.columns([1, 0.9, 1, 2.6], vertical_alignment="center")
            dec_col.button("−", key=f"dec_{item_id}", on_click=change_quantity, args=(item_id, -1),
                           disabled=item["quantity"] <= 1, help=f"{item['name']} 수량 줄이기", width="stretch")
            qty_col.markdown(f"<div style='text-align:center;font-weight:700'>{item['quantity']}</div>",
                             unsafe_allow_html=True)
            inc_col.button("+", key=f"inc_{item_id}", on_click=change_quantity, args=(item_id, 1),
                           disabled=item["quantity"] >= QTY_MAX, help=f"{item['name']} 수량 늘리기", width="stretch")
            subtotal = (item["price"] or 0) * item["quantity"]
            sub_col.markdown(f"<div style='text-align:right;font-weight:700'>{format_won(subtotal)}</div>",
                             unsafe_allow_html=True)
            st.divider()

        total = sum((item["price"] or 0) * item["quantity"] for item in cart_items)
        k1, v1 = st.columns(2)
        k1.caption("총 아이템")
        v1.markdown(f"<div style='text-align:right;font-weight:700'>{len(cart_items)}개</div>",
                    unsafe_allow_html=True)
        k2, v2 = st.columns([1, 2], vertical_alignment="center")
        k2.caption("합계")
        v2.markdown(f"<div class='cart-total'>{format_won(total)}</div>", unsafe_allow_html=True)
        if any(item["price"] is None for item in cart_items):
            st.caption("가격 미입력 아이템은 0원으로 계산돼요.")
        st.button("장바구니 비우기", on_click=clear_cart, disabled=not cart_items, width="stretch")
