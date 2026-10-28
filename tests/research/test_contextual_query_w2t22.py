"""(W2-T22) الاستعلام الواعي بسياق المحادثة + حثّ المتابعة — اختبارات الوحدة.

الدافع الموثق (محادثة المالك 15، 2026-10-28 01:33→02:28Z):

- (د1) «ابحث انت واعطني ملخص» قُطِّرت إلى «انت و ملخص» فأجاب ويكيبيديا
  بملخصات مسلسلات («أنت أطرق بابي») بدل أخبار انتخابات الكنيست التي
  طلبها المستخدم قبلها بدقيقة — التقطير لم يكن يرى سياق المحادثة.
- (د3) «؟» (02:28:24) لم تطلق بحثًا إطلاقًا (لا research.started،
  web_used=false) فأجاب النموذج من ذاكرته المتقادمة أنه «لا يملك
  إنترنت مباشر» — وهي بالضبط رسالة الشكوى.
"""

from __future__ import annotations

import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2] / "src"))

from research import chat_research as cr  # noqa: E402


#: سيناريو المالك حرفيًا (محادثة 15).
OWNER_TOPIC = "اخبار انتخابات الكنسيت اليوم"
OWNER_FOLLOWUP = "ابحث انت واعطني ملخص"


def test_distillation_no_longer_yields_you_and_summary():
    """(د1) «ابحث انت واعطني ملخص» تُقطَّر إلى فراغ — لا «انت و ملخص»."""
    assert cr._distill_tokens(OWNER_FOLLOWUP) == []
    # التقطير القديم كان يعيد «انت و ملخص» — الاستعلام المُقطَّر للعرض
    # يعود للنص الأصلي (سلوك قديم محفوظ)، لكن الفحص الموضوعي يرى الفراغ.
    assert cr.build_search_query(OWNER_TOPIC) == OWNER_TOPIC


def test_followup_request_inherits_conversation_topic():
    """(د1) رسالة طلب بلا موضوع ترث استعلام آخر رسالة موضوعية."""
    outcome = cr.build_contextual_search_query(
        OWNER_FOLLOWUP, [OWNER_TOPIC, OWNER_FOLLOWUP])
    assert outcome["inherited"] is True
    assert outcome["reason"] == "inherited_topic"
    assert outcome["query"] == OWNER_TOPIC
    assert "انت" not in outcome["query"].split()
    assert "ملخص" not in outcome["query"].split()


def test_topic_bearing_message_used_as_is():
    """الرسالة ذات الموضوع تُستخدم كما هي — لا وراثة بلا داعٍ."""
    outcome = cr.build_contextual_search_query(OWNER_TOPIC, [])
    assert outcome["inherited"] is False
    assert outcome["reason"] == "own_topic"
    assert outcome["query"] == OWNER_TOPIC


def test_new_short_topic_is_not_merged_with_old():
    """«فرنسا» موضوع جديد مشروع — لا يُدمج مع موضوع المحادثة القديم."""
    outcome = cr.build_contextual_search_query(
        "فرنسا", [OWNER_TOPIC, OWNER_FOLLOWUP, "؟"])
    assert outcome["inherited"] is False
    assert outcome["query"] == "فرنسا"


def test_bare_question_mark_inherits_and_skips_thin_messages():
    """(د3) «؟» ترث موضوع المحادثة متجاوزةً الرسائل الوصفية الرقيقة."""
    history = [OWNER_TOPIC, OWNER_FOLLOWUP, "؟"]
    outcome = cr.build_contextual_search_query("؟", history)
    assert outcome["inherited"] is True
    assert outcome["query"] == OWNER_TOPIC


def test_no_topic_and_no_history_falls_back_gracefully():
    """لا موضوع ولا تاريخ — سلوك قديم محفوظ (استعلام الرسالة نفسها)."""
    outcome = cr.build_contextual_search_query(OWNER_FOLLOWUP, [])
    assert outcome["inherited"] is False
    assert outcome["reason"] == "no_topic"
    assert outcome["query"] == OWNER_FOLLOWUP


def test_english_followup_inherits_topic():
    """«search again» إنجليزيًا ترث الموضوع السابق (كلمات طلب لا موضوع)."""
    outcome = cr.build_contextual_search_query(
        "search again", ["knesset election results"])
    assert outcome["inherited"] is True
    assert outcome["query"] == "knesset election results"


def test_is_followup_urge_positive_variants():
    """«؟»/«والان»/«جرب الان»/«حاول مجددا»/«ليش؟» — حثّ متابعة."""
    for message in ("؟", "؟؟", "?", "والان", "جرب الان", "حاول مجددا",
                    "ليش؟", "لماذا", "retry", "why?"):
        assert cr.is_followup_urge(message) is True, message


def test_is_followup_urge_negative_variants():
    """الرسائل الفعلية ليست حثًّا — مهما كانت قصيرة أو استفهامية."""
    for message in ("اكتب لي قصة حزينة من 10 صفحات",
                    "شكرا جزيلا",
                    "اخبار الانتخابات؟",
                    "ما اخر اخبار اليوم؟",
                    "ساعدني في كتابة كود بايثون للمشروع",
                    "الجزيرة نت تغطية مباشرة للانتخابات في إسرائيل"):
        assert cr.is_followup_urge(message) is False, message


def test_clock_question_behavior_preserved():
    """(رجعية RLR-005) سؤال الساعة الصِرف يبقى سؤال ساعة."""
    assert cr.is_clock_question("ما هو اليوم؟") is True
    assert cr.is_clock_question("اخبار اليوم") is False
    assert cr.is_clock_question("أسعار الذهب اليوم") is False
