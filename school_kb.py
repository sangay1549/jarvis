import difflib
import re

NAME = "Langthel Lower Secondary School"

# common ways speech recognizers mangle "Langthel"
_NAME_VARIANTS = [
    "langthel", "langthil", "llss",
    "lengthy", "lenthel", "lanthel", "langtel", "langtle", "langel",
    "langele", "longel", "langlet", "lancet", "lambeth", "longtill",
]

FACTS = [
    "Full name: Langthel Lower Secondary School (LLSS); the name is also spelled Langthil.",
    "Location: Langthil Gewog, Trongsa District (Dzongkhag), central Bhutan, along the Sarpang-Gelephu-Trongsa highway near the Black Mountains.",
    "Type: government co-educational lower secondary school under the Dzongkhag Administration, Trongsa.",
    "Established: constructed in the 1970s; one of the oldest schools in Trongsa.",
    "Enrollment: 372 students as of 2026; earlier figures were about 350 in 2022 and about 330 in 2012, of whom 138 were boarders (78 girls and 60 boys).",
    "Principal mentioned in a 2012 news report: Kuenga Loday.",
    "In 2012 the school proactively screened students for vitamin and protein deficiency after similar cases appeared in other schools; affected students were referred to the Basic Health Unit and Trongsa hospital, and health officials gave nutrition talks.",
    "In 2022 parents and local leaders petitioned to upgrade the school to a higher secondary school because students had to travel about 50 kilometres to Trongsa or Zhemgang; about two acres of additional land were explored for the upgrade.",
    "The upgrade was considered unlikely at the time under the education policy that allowed only primary (pre-primary to class six) and secondary (class seven upward) categories.",
    "Langthil Gewog also has four primary schools and four NFE centres; the gewog is served by two BHUs and six ORCs.",
    "Part of Langthil Gewog falls within Jigme Singye Wangchuck National Park and marked biological corridors.",
    "Catchment area: it acts as the central hub for local students completing primary education from the surrounding primary schools across the gewog's five chiwogs (Langthil, Dangdung, Baling, Yuendrocholing and Jangbi).",
]

QA = [
    (("where", "location", "situated", "located", "district", "gewog"),
     NAME + " is in Langthil Gewog, Trongsa District, central Bhutan, along the Sarpang-Gelephu-Trongsa highway near the Black Mountains."),
    (("established", "founded", "built", "construction", "history", "oldest"),
     "It was constructed in the 1970s, making it one of the oldest schools in Trongsa."),
    (("students", "enrollment", "enrolment", "strength", "how many"),
     "There are 372 students as of 2026. Earlier figures were about 350 in 2022 and around 330 in 2012, including 138 boarders."),
    (("boarder", "boarding"),
     "As of 2012, 138 students stayed in the boarding facility: 78 girls and 60 boys."),
    (("principal", "head teacher", "headmaster"),
     "The principal mentioned in a 2012 news report was Kuenga Loday."),
    (("upgrade", "upgradation", "higher secondary", "high school"),
     "In 2022 parents and local leaders asked the district to upgrade it to a higher secondary school so children would not have to travel about 50 kilometres to Trongsa or Zhemgang. About two acres of additional land were explored, but the upgrade looked unlikely under the education policy of the time."),
    (("vitamin", "nutrition", "deficiency", "health"),
     "In 2012 the principal's quick action found students with vitamin and protein deficiencies after similar cases appeared in the news; they were referred to the Basic Health Unit and Trongsa hospital, and health officials gave nutrition talks at the school."),
    (("facilities", "nearby", "bhg", "bhu", "hospital", "centre", "center"),
     "Langthil Gewog has this lower secondary school, four primary schools and four NFE centres, served by two Basic Health Units and six outreach clinics."),
    (("national park", "park", "forest", "environment", "corridor"),
     "Part of Langthil Gewog falls within Jigme Singye Wangchuck National Park and marked biological corridors."),
    (("catchment", "chiwog", "chiwogs", "hub", "feeder", "come from", "villages"),
     "The school is the central hub for local students completing primary education from the surrounding "
     "primary schools across the gewog's five chiwogs: Langthil, Dangdung, Baling, Yuendrocholing and Jangbi."),
    (("class", "classes", "grade", "levels", "curriculum"),
     "It is a government lower secondary school. Under the structure discussed in 2022, primary covers pre-primary to class six, and secondary runs from class seven upward."),
]


_SCHOOL_CONTEXT = (
    "school", "students", "principal", "gewog", "trongsa", "boarding",
    "class", "classes", "teacher", "secondary", "lower",
)


def matches(text):
    t = text.lower()
    if re.search(r"\blangth(?:e|i)l\b|\bllss\b", t):
        return True
    if re.search(r"\b(my|our|the)\s+school\b", t):
        return True
    has_context = any(w in t for w in _SCHOOL_CONTEXT)
    if not has_context:
        return False
    for v in _NAME_VARIANTS[3:]:
        if v in t:
            return True
    tokens = re.findall(r"[a-z']+", t)
    for w in tokens:
        for tg in ("langthel", "langthil", "llss"):
            if difflib.SequenceMatcher(None, w, tg).ratio() >= 0.72:
                return True
    return False


def answer(text):
    t = text.lower()
    best = None
    best_score = 0
    for keys, ans in QA:
        score = sum(1 for k in keys if k in t)
        if score > best_score:
            best_score = score
            best = ans
    return best


def facts_block():
    return "\n".join("- " + f for f in FACTS)
