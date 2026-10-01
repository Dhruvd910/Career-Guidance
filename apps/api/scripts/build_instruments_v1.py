"""One-off: writes the first versions of the aptitude, skills, coding-check and academic
instruments (app/assessment/instruments/*.v1.json). Kept for review; from now on the JSON files
are the source of truth, and changing one needs a new version (app/assessment/loader.py).

All problems are original, written for MAYA. Where an answer can be computed, it is checked
below with an assertion rather than trusted.

    python scripts/build_instruments_v1.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OUT = ROOT / "app/assessment/instruments"
LETTERS = "abcd"


def text(en, hi):
    return {"en": en, "hi": hi}


def options(pairs):
    """[(en, hi), …] → options a, b, c, d."""
    return [{"key": LETTERS[n], "label": text(en, hi)} for n, (en, hi) in enumerate(pairs)]


def problem(key, form, dimension, difficulty, prompt, choices, answer, why, section, code=None):
    item = {"key": key, "type": "problem", "form": form, "dimension": dimension, "difficulty": difficulty,
            "section": section, "prompt": text(*prompt), "options": options(choices), "answer": answer,
            "explanation": text(*why)}
    if code:
        item["code"] = code
    return item


def write(instrument):
    path = OUT / f"{instrument['key']}.v{instrument['version']}.json"
    path.write_text(json.dumps(instrument, ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {path.relative_to(ROOT)}")


# ---------------------------------------------------------------- aptitude

NUM, LOG, VERB = "aptitude:numerical", "aptitude:logical", "aptitude:verbal"
SECTION = {NUM: text("Numbers", "संख्याएँ"), LOG: text("Logic", "तर्क"), VERB: text("Words", "शब्द")}

# Checked arithmetic, so a typo can't make a wrong answer "right".
assert 12 * 5 == 60 and 15 * 4 == 60
assert 24 * 2 == 48 and 26 + 11 == 37
assert 800 * 0.75 == 600 and 1200 * 0.8 == 960
assert 300 / (180 / 3) == 5 and 4 * 6 / 3 == 8
assert 4 * 15 - (10 + 12 + 20) == 18 and 5 * 12 - (8 + 10 + 14 + 15) == 13
assert 7 + 5 - 1 == 11 and 6 + 9 - 1 == 14
assert "".join(chr(ord(c) + 1) for c in "DOG") == "EPH" and "".join(chr(ord(c) + 1) for c in "DESK") == "EFTL"
DAYS = ["Monday", "Tuesday", "Wednesday", "Thursday", "Friday", "Saturday", "Sunday"]
assert DAYS[(DAYS.index("Friday") - 1 - 2) % 7] == "Tuesday"  # tomorrow Friday → today Thursday → −2
assert DAYS[(DAYS.index("Monday") + 1 + 2) % 7] == "Thursday"  # yesterday Monday → today Tuesday → +2


def aptitude_items():
    A, B = "A", "B"
    items = [
        # ---- form A ----
        problem("a_num_1", A, NUM, 1, ("A pen costs ₹12. How much do 5 pens cost?", "एक पेन ₹12 का है। 5 पेन कितने के होंगे?"),
                [("₹50", "₹50"), ("₹60", "₹60"), ("₹62", "₹62"), ("₹72", "₹72")], "b",
                ("12 × 5 = 60.", "12 × 5 = 60।"), SECTION[NUM]),
        problem("a_log_1", A, LOG, 1, ("Riya is taller than Aman. Aman is taller than Sara. Who is the shortest?",
                                       "रिया अमन से लंबी है। अमन सारा से लंबा है। सबसे छोटा कौन है?"),
                [("Riya", "रिया"), ("Aman", "अमन"), ("Sara", "सारा"), ("Can't tell", "पता नहीं चल सकता")], "c",
                ("Riya > Aman > Sara, so Sara is the shortest.", "रिया > अमन > सारा, इसलिए सारा सबसे छोटी है।"), SECTION[LOG]),
        problem("a_verb_1", A, VERB, 1, ("Which word means the opposite of 'ancient'?", "'प्राचीन' का विलोम (उल्टा) क्या है?"),
                [("old", "पुराना"), ("modern", "आधुनिक"), ("famous", "प्रसिद्ध"), ("broken", "टूटा हुआ")], "b",
                ("Ancient means very old; modern means new.", "प्राचीन यानी बहुत पुराना; आधुनिक यानी नया।"), SECTION[VERB]),
        problem("a_num_2", A, NUM, 2, ("What comes next: 3, 6, 12, 24 …?", "आगे क्या आएगा: 3, 6, 12, 24 …?"),
                [("30", "30"), ("36", "36"), ("48", "48"), ("42", "42")], "c",
                ("Each number doubles: 24 × 2 = 48.", "हर संख्या दोगुनी होती है: 24 × 2 = 48।"), SECTION[NUM]),
        problem("a_log_2", A, LOG, 2, ("All roses are flowers. Some flowers fade quickly. Does it follow that some roses fade quickly?",
                                       "सभी गुलाब फूल हैं। कुछ फूल जल्दी मुरझा जाते हैं। क्या इससे यह साबित होता है कि कुछ गुलाब जल्दी मुरझाते हैं?"),
                [("Yes", "हाँ"), ("No", "नहीं"), ("Can't tell from this", "इससे पता नहीं चल सकता")], "c",
                ("The flowers that fade quickly might not include any roses.",
                 "जो फूल जल्दी मुरझाते हैं, ज़रूरी नहीं कि उनमें कोई गुलाब हो।"), SECTION[LOG]),
        problem("a_verb_2", A, VERB, 2, ("Book is to reading as fork is to …?", "जैसे किताब का संबंध पढ़ने से है, वैसे ही काँटे (फ़ोर्क) का संबंध किससे है?"),
                [("drawing", "चित्र बनाने से"), ("writing", "लिखने से"), ("eating", "खाने से"), ("cooking", "पकाने से")], "c",
                ("A book is used for reading; a fork is used for eating.", "किताब पढ़ने के काम आती है; काँटा खाने के।"), SECTION[VERB]),
        problem("a_num_3", A, NUM, 2, ("A shirt costs ₹800. In a sale it is 25% off. What is the sale price?",
                                       "एक शर्ट ₹800 की है। सेल में 25% की छूट है। सेल में दाम क्या है?"),
                [("₹575", "₹575"), ("₹600", "₹600"), ("₹625", "₹625"), ("₹700", "₹700")], "b",
                ("25% of 800 is 200; 800 − 200 = 600.", "800 का 25% है 200; 800 − 200 = 600।"), SECTION[NUM]),
        problem("a_log_3", A, LOG, 2, ("If CAT is written as DBU, how is DOG written?", "अगर CAT को DBU लिखा जाए, तो DOG को कैसे लिखेंगे?"),
                [("EPH", "EPH"), ("EPG", "EPG"), ("DPH", "DPH"), ("FQI", "FQI")], "a",
                ("Each letter moves one step forward: D→E, O→P, G→H.", "हर अक्षर एक आगे खिसकता है: D→E, O→P, G→H।"), SECTION[LOG]),
        problem("a_verb_3", A, VERB, 2, ("Which is the odd one out: apple, mango, carrot, banana?", "इनमें से कौन अलग है: सेब, आम, गाजर, केला?"),
                [("apple", "सेब"), ("mango", "आम"), ("carrot", "गाजर"), ("banana", "केला")], "c",
                ("Carrot is a vegetable; the rest are fruits.", "गाजर सब्ज़ी है; बाक़ी फल हैं।"), SECTION[VERB]),
        problem("a_num_4", A, NUM, 3, ("A train travels 180 km in 3 hours. At the same speed, how long will it take to travel 300 km?",
                                       "एक ट्रेन 3 घंटे में 180 किलोमीटर जाती है। इसी रफ़्तार से 300 किलोमीटर में कितना समय लगेगा?"),
                [("4 hours", "4 घंटे"), ("4½ hours", "साढ़े 4 घंटे"), ("5 hours", "5 घंटे"), ("6 hours", "6 घंटे")], "c",
                ("60 km per hour, so 300 km takes 5 hours.", "60 किलोमीटर प्रति घंटा, तो 300 किलोमीटर में 5 घंटे।"), SECTION[NUM]),
        problem("a_log_4", A, LOG, 3, ("In a row of children, Meena is 7th from the left and 5th from the right. How many children are in the row?",
                                       "बच्चों की एक लाइन में मीना बाएँ से 7वीं और दाएँ से 5वीं है। लाइन में कितने बच्चे हैं?"),
                [("10", "10"), ("11", "11"), ("12", "12"), ("13", "13")], "b",
                ("7 + 5 counts Meena twice: 7 + 5 − 1 = 11.", "7 + 5 में मीना दो बार गिनी गई: 7 + 5 − 1 = 11।"), SECTION[LOG]),
        problem("a_verb_4", A, VERB, 3, ("'Although the test was difficult, most students finished it on time.' What does this tell us?",
                                         "'हालाँकि परीक्षा कठिन थी, फिर भी ज़्यादातर छात्रों ने उसे समय पर पूरा कर लिया।' इससे क्या पता चलता है?"),
                [("The test was easy", "परीक्षा आसान थी"), ("Most students did not finish", "ज़्यादातर छात्र पूरा नहीं कर पाए"),
                 ("Most finished even though it was hard", "कठिन होने के बावजूद ज़्यादातर ने पूरा किया"),
                 ("The test had no time limit", "परीक्षा में समय की कोई सीमा नहीं थी")], "c",
                ("'Although' means despite the difficulty, they finished.", "'हालाँकि' यानी कठिनाई के बावजूद उन्होंने पूरा किया।"), SECTION[VERB]),
        problem("a_num_5", A, NUM, 3, ("The average of four numbers is 15. Three of them are 10, 12 and 20. What is the fourth?",
                                       "चार संख्याओं का औसत 15 है। उनमें से तीन हैं 10, 12 और 20। चौथी संख्या क्या है?"),
                [("15", "15"), ("18", "18"), ("20", "20"), ("28", "28")], "b",
                ("Four numbers averaging 15 add up to 60; 60 − 42 = 18.", "चार संख्याओं का औसत 15 तो जोड़ 60; 60 − 42 = 18।"), SECTION[NUM]),
        problem("a_log_5", A, LOG, 3, ("If tomorrow is Friday, what day was the day before yesterday?",
                                       "अगर आने वाला कल शुक्रवार है, तो बीता हुआ परसों कौन सा दिन था?"),
                [("Monday", "सोमवार"), ("Tuesday", "मंगलवार"), ("Wednesday", "बुधवार"), ("Thursday", "गुरुवार")], "b",
                ("Today is Thursday, so the day before yesterday was Tuesday.", "आज गुरुवार है, तो बीता हुआ परसों मंगलवार था।"), SECTION[LOG]),
        problem("a_verb_5", A, VERB, 3, ("Which word is closest in meaning to 'reluctant'?", "'हिचकिचाहट' के सबसे क़रीबी अर्थ वाला शब्द कौन सा है?"),
                [("eager", "उत्साह"), ("unwilling", "झिझक"), ("careful", "सावधानी"), ("angry", "ग़ुस्सा")], "b",
                ("Reluctant means not wanting to do something.", "हिचकिचाहट यानी झिझक, कुछ करने में संकोच।"), SECTION[VERB]),
        # ---- form B: the same kinds of problem, different content ----
        problem("b_num_1", B, NUM, 1, ("A notebook costs ₹15. How much do 4 notebooks cost?", "एक कॉपी ₹15 की है। 4 कॉपियाँ कितने की होंगी?"),
                [("₹45", "₹45"), ("₹55", "₹55"), ("₹60", "₹60"), ("₹65", "₹65")], "c",
                ("15 × 4 = 60.", "15 × 4 = 60।"), SECTION[NUM]),
        problem("b_log_1", B, LOG, 1, ("Ravi is older than Kiran. Kiran is older than Neha. Who is the oldest?",
                                       "रवि किरण से बड़ा है। किरण नेहा से बड़ी है। सबसे बड़ा कौन है?"),
                [("Ravi", "रवि"), ("Kiran", "किरण"), ("Neha", "नेहा"), ("Can't tell", "पता नहीं चल सकता")], "a",
                ("Ravi > Kiran > Neha, so Ravi is the oldest.", "रवि > किरण > नेहा, इसलिए रवि सबसे बड़ा है।"), SECTION[LOG]),
        problem("b_verb_1", B, VERB, 1, ("Which word means the opposite of 'generous'?", "'उदार' का विलोम (उल्टा) क्या है?"),
                [("kind", "दयालु"), ("stingy", "कंजूस"), ("rich", "अमीर"), ("brave", "बहादुर")], "b",
                ("Generous people give freely; stingy people don't.", "उदार व्यक्ति खुलकर देता है; कंजूस नहीं।"), SECTION[VERB]),
        problem("b_num_2", B, NUM, 2, ("What comes next: 2, 5, 10, 17, 26 …?", "आगे क्या आएगा: 2, 5, 10, 17, 26 …?"),
                [("35", "35"), ("36", "36"), ("37", "37"), ("38", "38")], "c",
                ("The gaps are 3, 5, 7, 9 — next is 11: 26 + 11 = 37.", "अंतर 3, 5, 7, 9 हैं — अगला 11: 26 + 11 = 37।"), SECTION[NUM]),
        problem("b_log_2", B, LOG, 2, ("Some students in a class play chess. Every chess player in the class is in the maths club. Which must be true?",
                                       "एक क्लास के कुछ छात्र शतरंज खेलते हैं। क्लास का हर शतरंज खिलाड़ी मैथ्स क्लब में है। क्या ज़रूर सच है?"),
                [("Every student is in the maths club", "हर छात्र मैथ्स क्लब में है"),
                 ("Some students are in the maths club", "कुछ छात्र मैथ्स क्लब में हैं"),
                 ("No student is in the maths club", "कोई छात्र मैथ्स क्लब में नहीं है"),
                 ("Everyone in the maths club plays chess", "मैथ्स क्लब का हर सदस्य शतरंज खेलता है")], "b",
                ("The chess players are students, and they are all in the club.", "शतरंज खिलाड़ी छात्र हैं, और वे सब क्लब में हैं।"), SECTION[LOG]),
        problem("b_verb_2", B, VERB, 2, ("Doctor is to hospital as teacher is to …?", "जैसे डॉक्टर का संबंध अस्पताल से है, वैसे ही शिक्षक का संबंध किससे है?"),
                [("library", "पुस्तकालय"), ("school", "स्कूल"), ("office", "दफ़्तर"), ("market", "बाज़ार")], "b",
                ("A doctor works in a hospital; a teacher works in a school.", "डॉक्टर अस्पताल में काम करता है; शिक्षक स्कूल में।"), SECTION[VERB]),
        problem("b_num_3", B, NUM, 2, ("A bag costs ₹1,200. In a sale it is 20% off. What is the sale price?",
                                       "एक बैग ₹1,200 का है। सेल में 20% की छूट है। सेल में दाम क्या है?"),
                [("₹940", "₹940"), ("₹960", "₹960"), ("₹980", "₹980"), ("₹1,000", "₹1,000")], "b",
                ("20% of 1,200 is 240; 1,200 − 240 = 960.", "1,200 का 20% है 240; 1,200 − 240 = 960।"), SECTION[NUM]),
        problem("b_log_3", B, LOG, 2, ("If BOOK is written as CPPL, how is DESK written?", "अगर BOOK को CPPL लिखा जाए, तो DESK को कैसे लिखेंगे?"),
                [("EFTL", "EFTL"), ("EFSL", "EFSL"), ("DFTL", "DFTL"), ("EETL", "EETL")], "a",
                ("Each letter moves one step forward: D→E, E→F, S→T, K→L.", "हर अक्षर एक आगे खिसकता है: D→E, E→F, S→T, K→L।"), SECTION[LOG]),
        problem("b_verb_3", B, VERB, 2, ("Which is the odd one out: chair, table, sofa, spoon?", "इनमें से कौन अलग है: कुर्सी, मेज़, सोफ़ा, चम्मच?"),
                [("chair", "कुर्सी"), ("table", "मेज़"), ("sofa", "सोफ़ा"), ("spoon", "चम्मच")], "d",
                ("A spoon isn't furniture.", "चम्मच फ़र्नीचर नहीं है।"), SECTION[VERB]),
        problem("b_num_4", B, NUM, 3, ("4 workers build a wall in 6 days. How many days would 3 workers take, working at the same rate?",
                                       "4 मज़दूर एक दीवार 6 दिन में बनाते हैं। उसी रफ़्तार से 3 मज़दूरों को कितने दिन लगेंगे?"),
                [("4½ days", "साढ़े 4 दिन"), ("7 days", "7 दिन"), ("8 days", "8 दिन"), ("9 days", "9 दिन")], "c",
                ("The wall takes 4 × 6 = 24 worker-days; 24 ÷ 3 = 8.", "दीवार में 4 × 6 = 24 मज़दूर-दिन लगते हैं; 24 ÷ 3 = 8।"), SECTION[NUM]),
        problem("b_log_4", B, LOG, 3, ("In a queue, Arjun is 6th from the front and 9th from the back. How many people are in the queue?",
                                       "एक कतार में अर्जुन आगे से 6वाँ और पीछे से 9वाँ है। कतार में कितने लोग हैं?"),
                [("13", "13"), ("14", "14"), ("15", "15"), ("16", "16")], "b",
                ("6 + 9 counts Arjun twice: 6 + 9 − 1 = 14.", "6 + 9 में अर्जुन दो बार गिना गया: 6 + 9 − 1 = 14।"), SECTION[LOG]),
        problem("b_verb_4", B, VERB, 3, ("'The shop opens only from Monday to Friday, and today it is open.' What can we say about today?",
                                         "'दुकान सिर्फ़ सोमवार से शुक्रवार तक खुलती है, और आज खुली है।' आज के बारे में क्या कह सकते हैं?"),
                [("It is a Sunday", "आज रविवार है"), ("It is a day from Monday to Friday", "आज सोमवार से शुक्रवार के बीच का दिन है"),
                 ("The shop is closing soon", "दुकान जल्दी बंद होने वाली है"), ("It is a holiday", "आज छुट्टी है")], "b",
                ("It opens only Monday to Friday, so today must be one of those days.",
                 "दुकान सिर्फ़ सोमवार से शुक्रवार खुलती है, तो आज उन्हीं में से कोई दिन है।"), SECTION[VERB]),
        problem("b_num_5", B, NUM, 3, ("The average of five numbers is 12. Four of them are 8, 10, 14 and 15. What is the fifth?",
                                       "पाँच संख्याओं का औसत 12 है। उनमें से चार हैं 8, 10, 14 और 15। पाँचवीं संख्या क्या है?"),
                [("11", "11"), ("12", "12"), ("13", "13"), ("15", "15")], "c",
                ("Five numbers averaging 12 add up to 60; 60 − 47 = 13.", "पाँच संख्याओं का औसत 12 तो जोड़ 60; 60 − 47 = 13।"), SECTION[NUM]),
        problem("b_log_5", B, LOG, 3, ("If yesterday was Monday, what day will it be the day after tomorrow?",
                                       "अगर बीता हुआ कल सोमवार था, तो आने वाला परसों कौन सा दिन होगा?"),
                [("Wednesday", "बुधवार"), ("Thursday", "गुरुवार"), ("Friday", "शुक्रवार"), ("Saturday", "शनिवार")], "b",
                ("Today is Tuesday, so the day after tomorrow is Thursday.", "आज मंगलवार है, तो आने वाला परसों गुरुवार।"), SECTION[LOG]),
        problem("b_verb_5", B, VERB, 3, ("Which word is closest in meaning to 'abundant'?", "'प्रचुर' का सबसे क़रीबी अर्थ क्या है?"),
                [("rare", "दुर्लभ"), ("plentiful", "भरपूर"), ("empty", "ख़ाली"), ("costly", "महँगा")], "b",
                ("Abundant means more than enough.", "प्रचुर यानी ज़रूरत से ज़्यादा, भरपूर।"), SECTION[VERB]),
    ]
    return items


def aptitude():
    return {
        "key": "aptitude", "version": 1, "category": "aptitude",
        "title": text("Thinking skills", "सोचने की क्षमता"),
        "about": text("15 short problems with numbers, logic and words. It shows how you did today — it isn't an IQ test "
                      "and doesn't decide anything about you.",
                      "संख्याओं, तर्क और शब्दों के 15 छोटे सवाल। यह बताता है कि आज आपने कैसा किया — यह IQ टेस्ट नहीं है "
                      "और आपके बारे में कुछ तय नहीं करता।"),
        "intro": text("Fifteen short problems — numbers, logic and words. Take your time; if you're not sure, have a go "
                      "or say skip. This isn't an exam, it just shows how you think.",
                      "पंद्रह छोटे सवाल — संख्याएँ, तर्क और शब्द। आराम से कीजिए; पक्का न हो तो अंदाज़ा लगाइए या 'छोड़ो' कहिए। "
                      "यह परीक्षा नहीं है, बस यह दिखाता है कि आप कैसे सोचते हैं।"),
        "scoring_method": "correct_answers", "est_minutes": 10, "forms": ["A", "B"],
        "dimensions": {
            NUM: {"en": "working with numbers", "hi": "संख्याओं के साथ काम", "group": "aptitude"},
            LOG: {"en": "logical reasoning", "hi": "तार्किक सोच", "group": "aptitude"},
            VERB: {"en": "understanding words", "hi": "शब्दों की समझ", "group": "aptitude"},
        },
        "items": aptitude_items(),
    }


# ---------------------------------------------------------------- skills (self-report, anchored)

def anchored(key, dimension, name, prompt, levels):
    return {"key": key, "type": "anchored", "dimension": dimension, "section": text(*name), "prompt": text(*prompt),
            "options": [{"key": f"l{n}", "level": n, "label": text(en, hi)} for n, (en, hi) in enumerate(levels)]}


def skills():
    items = [
        anchored("programming", "skill:programming", ("Coding", "कोडिंग"),
                 ("Coding — which is most like you?", "कोडिंग — इनमें से आप पर सबसे ज़्यादा क्या लागू होता है?"), [
                     ("I've never written code", "मैंने कभी कोड नहीं लिखा"),
                     ("I've followed a tutorial or done class exercises", "मैंने कोई ट्यूटोरियल या क्लास की एक्सरसाइज़ की है"),
                     ("I've built something small on my own — a game, a website, a script",
                      "मैंने ख़ुद कुछ छोटा बनाया है — कोई गेम, वेबसाइट या स्क्रिप्ट"),
                     ("I code regularly, or I've built something other people use",
                      "नियमित कोडिंग मेरी आदत है, या मैंने कुछ ऐसा बनाया है जो दूसरे इस्तेमाल करते हैं"),
                 ]),
        anchored("speaking", "skill:speaking", ("Speaking", "बोलना"),
                 ("Speaking in front of people — which is most like you?", "लोगों के सामने बोलना — इनमें से आप पर क्या लागू होता है?"), [
                     ("I avoid it", "इससे बचना ही पसंद है"),
                     ("I can if I have to, with notes", "ज़रूरत पड़ने पर नोट्स देखकर बोलना आता है"),
                     ("I've spoken at assemblies, debates or presentations a few times",
                      "मैंने कुछ बार असेंबली, डिबेट या प्रेज़ेंटेशन में बोला है"),
                     ("I often present or debate, and people say I'm good at it",
                      "प्रेज़ेंटेशन और डिबेट मेरे लिए आम बात है, और लोग मेरे बोलने की तारीफ़ करते हैं"),
                 ]),
        anchored("writing", "skill:writing", ("Writing", "लिखना"),
                 ("Writing — which is most like you?", "लिखना — इनमें से आप पर क्या लागू होता है?"), [
                     ("I only write for school when I have to", "लिखना सिर्फ़ स्कूल के लिए, जब ज़रूरी हो"),
                     ("I can write a clear essay or letter", "साफ़-साफ़ निबंध या पत्र लिखना आता है"),
                     ("I write on my own — stories, a blog, a diary", "अपने मन से लिखना — कहानियाँ, ब्लॉग, डायरी"),
                     ("Others regularly read my writing, or it has won something",
                      "दूसरे मेरा लिखा नियमित पढ़ते हैं, या उसने कोई इनाम जीता है"),
                 ]),
        anchored("design", "skill:design", ("Drawing and design", "ड्रॉइंग और डिज़ाइन"),
                 ("Drawing and design — which is most like you?", "ड्रॉइंग और डिज़ाइन — इनमें से आप पर क्या लागू होता है?"), [
                     ("I don't really draw or design", "ड्रॉइंग या डिज़ाइन से ज़्यादा वास्ता नहीं"),
                     ("I doodle, or make school projects look nice", "कभी-कभी स्केच, या स्कूल प्रोजेक्ट को सुंदर बनाना"),
                     ("I've made posters, artwork or digital designs on my own",
                      "मैंने ख़ुद पोस्टर, आर्टवर्क या डिजिटल डिज़ाइन बनाए हैं"),
                     ("People ask me to design things, or my work has been shown or won something",
                      "लोग मुझसे डिज़ाइन करवाते हैं, या मेरा काम दिखाया गया है या जीता है"),
                 ]),
        anchored("hands_on", "skill:hands_on", ("Building and fixing", "बनाना और ठीक करना"),
                 ("Building and fixing things — which is most like you?", "चीज़ें बनाना और ठीक करना — इनमें से आप पर क्या लागू होता है?"), [
                     ("I haven't really tried", "मैंने ज़्यादा कोशिश नहीं की"),
                     ("I've helped fix or put something together", "मैंने कुछ ठीक करने या जोड़ने में मदद की है"),
                     ("I've built a model, circuit or gadget on my own", "मैंने ख़ुद कोई मॉडल, सर्किट या गैजेट बनाया है"),
                     ("I often build or repair things, and they work", "अक्सर चीज़ें बनाना या ठीक करना, और वे सच में चलती हैं"),
                 ]),
        anchored("leadership", "skill:leadership", ("Leading", "नेतृत्व"),
                 ("Leading a group — which is most like you?", "किसी ग्रुप को लीड करना — इनमें से आप पर क्या लागू होता है?"), [
                     ("I'd rather not lead", "लीड न करना ही पसंद है"),
                     ("I've led a small part of a group project", "मैंने ग्रुप प्रोजेक्ट का कोई छोटा हिस्सा लीड किया है"),
                     ("I've been a monitor or captain, or organised an event", "मॉनिटर या कैप्टन बनने का मौक़ा मिला है, या मैंने कोई इवेंट आयोजित किया है"),
                     ("I've led a team or club for a long time", "मैंने लंबे समय तक कोई टीम या क्लब लीड किया है"),
                 ]),
        anchored("organising", "skill:organising", ("Planning", "योजना बनाना"),
                 ("Planning and organising — which is most like you?", "योजना बनाना और व्यवस्थित रहना — इनमें से आप पर क्या लागू होता है?"), [
                     ("I usually do things at the last minute", "अक्सर काम आख़िरी समय पर होता है"),
                     ("I make plans but often don't follow them", "योजना बनती है, पर अक्सर उस पर चलना नहीं हो पाता"),
                     ("I keep a timetable or to-do list most of the time", "ज़्यादातर समय टाइमटेबल या टू-डू लिस्ट रहती है"),
                     ("I plan well, and others rely on me to organise things",
                      "अच्छी योजना बनाना आता है, और दूसरे चीज़ें व्यवस्थित करने के लिए मुझ पर भरोसा करते हैं"),
                 ]),
        anchored("english", "skill:english", ("English", "अंग्रेज़ी"),
                 ("English — which is most like you?", "अंग्रेज़ी — इनमें से आप पर क्या लागू होता है?"), [
                     ("I find it hard to understand or speak", "मुझे समझने और बोलने में मुश्किल होती है"),
                     ("I understand most of it, but speaking is hard", "ज़्यादातर समझ आती है, पर बोलना मुश्किल है"),
                     ("I can talk and write in everyday English comfortably", "रोज़मर्रा की अंग्रेज़ी आराम से बोलना और लिखना आता है"),
                     ("I'm fluent — I read books and speak easily in English", "धाराप्रवाह — अंग्रेज़ी की किताबें पढ़ना और आसानी से बोलना"),
                 ]),
    ]
    return {
        "key": "skills", "version": 1, "category": "skill",
        "title": text("Your skills", "आपके हुनर"),
        "about": text("Eight skills. For each, pick the line most like you — what you've actually done, not what you hope to do.",
                      "आठ हुनर। हर एक के लिए वह लाइन चुनिए जो आप पर सबसे ज़्यादा लागू हो — जो आपने सच में किया है, जो आप करना चाहते हैं वह नहीं।"),
        "intro": text("Now eight skills. For each one I'll read four lines — pick the one most like you, by what you've "
                      "actually done so far. You can say the number.",
                      "अब आठ हुनर। हर एक के लिए मैं चार लाइनें पढ़ूँगी — जो आप पर सबसे ज़्यादा लागू हो, वह चुनिए, जो आपने अब तक "
                      "सच में किया है उसके हिसाब से। आप नंबर बोल सकते हैं।"),
        "scoring_method": "anchored_levels", "est_minutes": 3,
        "dimensions": {
            "skill:programming": {"en": "coding", "hi": "कोडिंग", "group": "skill"},
            "skill:speaking": {"en": "speaking in front of people", "hi": "लोगों के सामने बोलना", "group": "skill"},
            "skill:writing": {"en": "writing", "hi": "लिखना", "group": "skill"},
            "skill:design": {"en": "drawing and design", "hi": "ड्रॉइंग और डिज़ाइन", "group": "skill"},
            "skill:hands_on": {"en": "building and fixing things", "hi": "चीज़ें बनाना और ठीक करना", "group": "skill"},
            "skill:leadership": {"en": "leading a group", "hi": "ग्रुप को लीड करना", "group": "skill"},
            "skill:organising": {"en": "planning and organising", "hi": "योजना बनाना और व्यवस्थित रहना", "group": "skill"},
            "skill:english": {"en": "English", "hi": "अंग्रेज़ी", "group": "skill"},
        },
        "items": items,
    }


# ---------------------------------------------------------------- the coding check

CODE = text("Code", "कोड")


def _run(code: str, var: str):
    """Checks a pseudo-code answer by running the same logic as Python."""
    scope: dict = {}
    exec(code, {}, scope)  # noqa: S102 — our own literal snippets, written just below
    return scope[var]


assert _run("x = 5\nx = x + 3", "x") == 8
assert _run("a = 4\nb = a * 2\na = 10", "b") == 8
assert _run("total = 0\nfor i in range(1, 5):\n    total = total + i", "total") == 10
assert _run("count = 0\nfor letter in 'banana':\n    if letter == 'a':\n        count = count + 1", "count") == 3
assert _run("n = 1\nwhile n < 20:\n    n = n * 3", "n") == 27
assert _run("nums = [4, 9, 2, 7]\nbiggest = nums[0]\nfor x in nums:\n    if x > biggest:\n        biggest = x", "biggest") == 9
assert _run("a = 3\nb = 5\nt = a\na = b\nb = t", "a") == 5


def coding_items():
    dim = "check:programming"
    look = ("Look at the code on the screen.", "स्क्रीन पर कोड देखिए।")
    return [
        problem("c1", None, dim, 1, ("What is x at the end?", "आख़िर में x क्या है?"),
                [("5", "5"), ("8", "8"), ("3", "3"), ("53", "53")], "b",
                ("x starts at 5, then becomes 5 + 3 = 8.", "x पहले 5 है, फिर 5 + 3 = 8 हो जाता है।"), CODE, code="x = 5\nx = x + 3"),
        problem("c2", None, dim, 1, ("What is b at the end?", "आख़िर में b क्या है?"),
                [("8", "8"), ("20", "20"), ("10", "10"), ("4", "4")], "a",
                ("b was worked out when a was 4; changing a later doesn't change b.",
                 "b तब निकला जब a = 4 था; बाद में a बदलने से b नहीं बदलता।"), CODE, code="a = 4\nb = a * 2\na = 10"),
        problem("c3", None, dim, 2, ("What is printed when marks is 33?", "जब marks 33 हो, तो क्या छपेगा?"),
                [("pass", "pass"), ("fail", "fail"), ("nothing", "कुछ नहीं"), ("an error", "एरर")], "a",
                (">= means 'at least', so 33 passes.", ">= का मतलब 'कम से कम', इसलिए 33 पास है।"), CODE,
                code="if marks >= 33:\n    print(\"pass\")\nelse:\n    print(\"fail\")"),
        problem("c4", None, dim, 2, ("What is total at the end?", "आख़िर में total क्या है?"),
                [("4", "4"), ("10", "10"), ("6", "6"), ("24", "24")], "b",
                ("1 + 2 + 3 + 4 = 10.", "1 + 2 + 3 + 4 = 10।"), CODE,
                code="total = 0\nrepeat for i = 1 to 4:\n    total = total + i"),
        problem("c5", None, dim, 2, ("What is count at the end?", "आख़िर में count क्या है?"),
                [("2", "2"), ("3", "3"), ("6", "6"), ("1", "1")], "b",
                ("'banana' has three a's.", "'banana' में तीन a हैं।"), CODE,
                code="count = 0\nfor each letter in \"banana\":\n    if letter == \"a\":\n        count = count + 1"),
        problem("c6", None, dim, 3, ("What is n at the end?", "आख़िर में n क्या है?"),
                [("9", "9"), ("20", "20"), ("27", "27"), ("81", "81")], "c",
                ("n goes 1 → 3 → 9 → 27, and stops because 27 is not less than 20.",
                 "n: 1 → 3 → 9 → 27, और रुक जाता है क्योंकि 27, 20 से कम नहीं है।"), CODE,
                code="n = 1\nwhile n < 20:\n    n = n * 3"),
        problem("c7", None, dim, 3, ("What is biggest at the end?", "आख़िर में biggest क्या है?"),
                [("4", "4"), ("7", "7"), ("9", "9"), ("2", "2")], "c",
                ("It keeps the largest number it has seen: 9.", "यह अब तक की सबसे बड़ी संख्या रखता है: 9।"), CODE,
                code="nums = [4, 9, 2, 7]\nbiggest = nums[0]\nfor each x in nums:\n    if x > biggest:\n        biggest = x"),
        problem("c8", None, dim, 3, ("a is 3 and b is 5. Which steps swap them, so a is 5 and b is 3?",
                                     "a = 3 और b = 5 है। कौन से स्टेप इन्हें अदल-बदल देंगे, ताकि a = 5 और b = 3 हो?"),
                [("a = b, then b = a", "a = b, फिर b = a"), ("t = a, then a = b, then b = t", "t = a, फिर a = b, फिर b = t"),
                 ("b = a, then a = b", "b = a, फिर a = b"), ("a = a + b", "a = a + b")], "b",
                ("Without a spare variable, the first copy overwrites a value you still need.",
                 "एक अतिरिक्त वेरिएबल के बिना पहली ही कॉपी वह मान मिटा देती है जिसकी ज़रूरत है।"), CODE),
    ], look


def coding_check():
    items, look = coding_items()
    for item in items:
        if "code" in item:
            item["speak"] = {"en": f"{look[0]} {item['prompt']['en']}", "hi": f"{look[1]} {item['prompt']['hi']}"}
    return {
        "key": "coding_check", "version": 1, "category": "skill",
        "title": text("Coding check", "कोडिंग जाँच"),
        "about": text("8 short pieces of code to read — no programming language needed. Best done on the screen.",
                      "पढ़ने के लिए कोड के 8 छोटे टुकड़े — कोई प्रोग्रामिंग भाषा आना ज़रूरी नहीं। स्क्रीन पर करना सबसे अच्छा है।"),
        "intro": text("Eight short pieces of code. You don't need to know any programming language — just follow what "
                      "each line does. It's easiest on the screen.",
                      "कोड के आठ छोटे टुकड़े। कोई प्रोग्रामिंग भाषा आना ज़रूरी नहीं — बस देखिए कि हर लाइन क्या करती है। "
                      "स्क्रीन पर करना सबसे आसान है।"),
        "scoring_method": "correct_answers", "est_minutes": 6,
        "dimensions": {"check:programming": {"en": "reading code", "hi": "कोड पढ़ना", "group": "skill"}},
        "items": items,
    }


# ---------------------------------------------------------------- academic profile

SUBJECTS = {  # key: (English, Hindi)
    "maths": ("Maths", "मैथ्स"), "science": ("Science", "विज्ञान"), "social_science": ("Social science", "सामाजिक विज्ञान"),
    "english": ("English", "अंग्रेज़ी"), "hindi": ("Hindi", "हिंदी"), "physics": ("Physics", "फ़िज़िक्स"),
    "chemistry": ("Chemistry", "केमिस्ट्री"), "biology": ("Biology", "बायोलॉजी"),
    "computer": ("Computer science", "कंप्यूटर साइंस"), "accountancy": ("Accountancy", "अकाउंटेंसी"),
    "business_studies": ("Business studies", "बिज़नेस स्टडीज़"), "economics": ("Economics", "अर्थशास्त्र"),
    "history": ("History", "इतिहास"), "political_science": ("Political science", "राजनीति विज्ञान"),
    "geography": ("Geography", "भूगोल"),
}
SENIOR_BY_STREAM = {  # class 11-12: which subjects to ask about, by stream
    "physics": ["pcm", "pcb", "pcmb"], "chemistry": ["pcm", "pcb", "pcmb"], "maths": ["pcm", "pcmb", "commerce"],
    "biology": ["pcb", "pcmb"], "computer": ["pcm"], "accountancy": ["commerce"], "business_studies": ["commerce"],
    "economics": ["commerce", "humanities"], "history": ["humanities"], "political_science": ["humanities"],
    "geography": ["humanities"],
}


def marks(key, subject, classes, requires=None):
    en, hi = SUBJECTS[subject]
    item = {"key": key, "type": "marks", "dimension": f"academic:{subject}", "section": text("Marks", "अंक"),
            "prompt": text(f"{en}: what percentage did you get in your last exam?",
                           f"{hi}: पिछली परीक्षा में कितने प्रतिशत अंक आए?"),
            "speak": text(f"{en} — what percentage did you get in your last exam? Say skip if you don't take it.",
                          f"{hi} — पिछली परीक्षा में कितने प्रतिशत अंक आए? अगर यह विषय नहीं है तो 'छोड़ो' कहिए।"),
            "applies_to": {"class_levels": classes}}
    if requires:
        item["requires"] = requires
    return item


def academic():
    junior = list(range(6, 11))
    senior = [11, 12]
    items = [marks(f"jr_{s}", s, junior) for s in ("maths", "science", "social_science", "english", "hindi")]
    items.append({
        "key": "stream", "type": "choice", "section": text("Marks", "अंक"),
        "prompt": text("Which stream are you in?", "आप किस स्ट्रीम में हैं?"),
        "speak": text("Which stream are you in? PCM, PCB, PCMB, commerce or humanities?",
                      "आप किस स्ट्रीम में हैं? पी.सी.एम., पी.सी.बी., पी.सी.एम.बी., कॉमर्स या ह्यूमैनिटीज़?"),
        "applies_to": {"class_levels": senior},
        "options": [
            {"key": "pcm", "label": text("PCM", "PCM"), "keywords": {"en": ["pcm", "maths", "non medical", "non-medical"], "hinglish": [], "hi": ["पीसीएम"]}},
            {"key": "pcb", "label": text("PCB", "PCB"), "keywords": {"en": ["pcb", "bio", "medical"], "hinglish": [], "hi": ["पीसीबी"]}},
            {"key": "pcmb", "label": text("PCMB", "PCMB"), "keywords": {"en": ["pcmb", "both"], "hinglish": ["dono"], "hi": ["पीसीएमबी", "दोनों"]}},
            {"key": "commerce", "label": text("Commerce", "कॉमर्स"), "keywords": {"en": ["commerce"], "hinglish": [], "hi": ["कॉमर्स"]}},
            {"key": "humanities", "label": text("Humanities / Arts", "ह्यूमैनिटीज़ / आर्ट्स"),
             "keywords": {"en": ["humanities", "arts"], "hinglish": [], "hi": ["आर्ट्स", "ह्यूमैनिटीज़"]}},
        ],
    })
    items += [marks(f"sr_{s}", s, senior, {"stream": streams}) for s, streams in SENIOR_BY_STREAM.items()]
    items.append(marks("sr_english", "english", senior))
    return {
        "key": "academic", "version": 1, "category": "academic",
        "title": text("Your marks", "आपके अंक"),
        "about": text("Your latest marks, subject by subject. Skip any subject you don't take.",
                      "विषय के हिसाब से आपके सबसे हाल के अंक। जो विषय आपके पास नहीं है, उसे छोड़ दीजिए।"),
        "intro": text("Let's note down your latest marks. Just tell me the percentage for each subject, or skip ones you don't take.",
                      "चलिए आपके हाल के अंक लिख लेते हैं। हर विषय का प्रतिशत बताइए, या जो विषय नहीं है उसे छोड़ दीजिए।"),
        "scoring_method": "marks", "est_minutes": 2,
        "dimensions": {f"academic:{k}": {"en": f"{en} marks", "hi": f"{hi} के अंक", "group": "academic"}
                       for k, (en, hi) in SUBJECTS.items()},
        "items": items,
    }


if __name__ == "__main__":
    for build in (aptitude, skills, coding_check, academic):
        write(build())
