"""One-off: builds app/assessment/instruments/interests.v1.json from MAYA's original conversational
quiz (app/seed/assessment_questions.json, English only) plus the Hindi below and a short
"how you learn" section. Kept so the port can be reviewed; the JSON file is the source of
truth from now on (a change to it needs a new version — app/assessment/loader.py).

    python scripts/build_interests_v1.py
"""

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
OLD = json.loads((ROOT / "app/seed/assessment_questions.json").read_text())
OUT = ROOT / "app/assessment/instruments/interests.v1.json"

SECTIONS = {
    "Subjects": "विषय", "Maths": "मैथ्स", "Physics": "फ़िज़िक्स", "Chemistry": "केमिस्ट्री", "Biology": "बायोलॉजी",
    "Computers": "कंप्यूटर", "Business": "बिज़नेस", "Design": "डिज़ाइन", "Language": "भाषा",
    "Personality": "आपके बारे में", "Work style": "काम का तरीका", "What matters": "आपके लिए क्या ज़रूरी है",
}

# Hindi for each question: prompt, what MAYA says, and each option's label.
HI = {
    "int_maths": ("मैथ्स आपको कैसा लगता है?",
                  "चलिए विषयों से शुरू करते हैं। मैथ्स आपको कैसा लगता है? बहुत पसंद है, पसंद है, ज़्यादा नहीं, या मुश्किल लगता है?",
                  {"love": "बहुत पसंद है", "like": "पसंद है", "meh": "ज़्यादा नहीं", "hard": "मुश्किल लगता है"}),
    "maths_style": ("मैथ्स में आपको सबसे ज़्यादा क्या अच्छा लगता है?",
                    "मैथ्स में आपको सबसे ज़्यादा क्या अच्छा लगता है? पहेलियाँ और लॉजिक, नंबर और पैसे का हिसाब, आकार और ज्यामिति, या कैलकुलस और समीकरण?",
                    {"logic": "पहेलियाँ और लॉजिक", "money": "नंबर और पैसे का हिसाब", "shapes": "आकार और ज्यामिति",
                     "calculus": "कैलकुलस और समीकरण"}),
    "int_physics": ("और फ़िज़िक्स?", "और फ़िज़िक्स? बहुत पसंद, पसंद, ज़्यादा नहीं, या मुश्किल?",
                    {"love": "बहुत पसंद है", "like": "पसंद है", "meh": "ज़्यादा नहीं", "hard": "मुश्किल लगता है"}),
    "physics_side": ("फ़िज़िक्स का कौन सा हिस्सा आपको ज़्यादा रोमांचित करता है?",
                     "फ़िज़िक्स का कौन सा हिस्सा आपको ज़्यादा अच्छा लगता है? मशीनें और बिजली कैसे काम करती हैं, अंतरिक्ष और ब्रह्मांड, या न्यूमेरिकल हल करना?",
                     {"machines": "मशीनें और बिजली कैसे काम करती हैं", "universe": "अंतरिक्ष और ब्रह्मांड कैसे चलता है",
                      "numericals": "न्यूमेरिकल हल करना"}),
    "build_things": ("क्या आपको अपने हाथों से चीज़ें बनाना अच्छा लगेगा — सर्किट, रोबोट, इंजन?",
                     "क्या आपको अपने हाथों से चीज़ें बनाना अच्छा लगेगा, जैसे सर्किट, रोबोट या इंजन? हाँ, शायद, या नहीं?",
                     {"yes": "हाँ, बहुत", "maybe": "शायद, कभी-कभी", "no": "ज़्यादा नहीं"}),
    "int_chemistry": ("केमिस्ट्री के बारे में क्या ख़याल है?", "केमिस्ट्री के बारे में क्या ख़याल है? बहुत पसंद, पसंद, ज़्यादा नहीं, या मुश्किल?",
                      {"love": "बहुत पसंद है", "like": "पसंद है", "meh": "ज़्यादा नहीं", "hard": "मुश्किल लगता है"}),
    "chemistry_side": ("केमिस्ट्री में आपको क्या खींचता है?",
                       "केमिस्ट्री में आपको क्या अच्छा लगता है? लैब में प्रयोग करना, दवाइयाँ शरीर में कैसे काम करती हैं, या नए मटीरियल और ईंधन बनाना?",
                       {"lab": "लैब में प्रयोग करना", "medicines": "दवाइयाँ शरीर में कैसे काम करती हैं",
                        "materials": "नए मटीरियल और ईंधन बनाना"}),
    "int_biology": ("और बायोलॉजी?", "और बायोलॉजी? बहुत पसंद, पसंद, ज़्यादा नहीं, या मुश्किल?",
                    {"love": "बहुत पसंद है", "like": "पसंद है", "meh": "ज़्यादा नहीं", "hard": "मुश्किल लगता है"}),
    "biology_side": ("बायोलॉजी का कौन सा हिस्सा आपको सबसे दिलचस्प लगता है?",
                     "बायोलॉजी का कौन सा हिस्सा आपको सबसे दिलचस्प लगता है? मानव शरीर और सेहत, जानवर, पौधे और पर्यावरण, या जीन, कोशिकाएँ और रिसर्च?",
                     {"body": "मानव शरीर और सेहत", "nature": "जानवर, पौधे और पर्यावरण", "genes": "जीन, कोशिकाएँ और रिसर्च"}),
    "biology_role": ("अगर आप हेल्थ में काम करें, तो क्या करना चाहेंगे?",
                     "अगर आप हेल्थ में काम करें, तो क्या करना चाहेंगे? मरीज़ों की बीमारी पहचानकर इलाज करना, ठीक होते मरीज़ों की देखभाल, नए इलाज पर रिसर्च, या जानवरों की देखभाल?",
                     {"treat": "बीमारी पहचानना और इलाज करना", "care": "ठीक होते मरीज़ों की देखभाल",
                      "research": "नए इलाज पर रिसर्च", "animals": "जानवरों की देखभाल"}),
    "hospital": ("अस्पताल, खून और चोट से आपको कैसा लगता है?",
                 "अस्पताल, खून और चोट से आपको कैसा लगता है? बिल्कुल ठीक, थोड़ा-बहुत ठीक, या आप दूर रहना चाहेंगे?",
                 {"fine": "बिल्कुल ठीक", "okay": "थोड़ा-बहुत ठीक", "avoid": "दूर रहना ही ठीक"}),
    "int_computer": ("कंप्यूटर और कोडिंग आपको कितना अच्छा लगता है?",
                     "कंप्यूटर और कोडिंग आपको कितना अच्छा लगता है? बहुत, थोड़ा, ज़्यादा नहीं, या कभी आज़माया ही नहीं?",
                     {"love": "बहुत", "like": "थोड़ा", "meh": "ज़्यादा नहीं", "never": "कभी आज़माया नहीं"}),
    "computer_side": ("इनमें से सबसे मज़ेदार क्या लगता है?",
                      "इनमें से सबसे मज़ेदार क्या लगता है? ऐप और वेबसाइट बनाना, गेम और एनीमेशन बनाना, या डेटा और ए.आई. से कंप्यूटर को सिखाना?",
                      {"apps": "ऐप और वेबसाइट बनाना", "games": "गेम, ग्राफ़िक्स और एनीमेशन", "ai": "डेटा और ए.आई."}),
    "int_commerce": ("क्या बिज़नेस, पैसा और अर्थव्यवस्था आपको दिलचस्प लगते हैं?",
                     "क्या बिज़नेस, पैसा और अर्थव्यवस्था आपको दिलचस्प लगते हैं? बहुत, थोड़ा, या बिल्कुल नहीं?",
                     {"love": "बहुत दिलचस्प", "like": "थोड़ा", "no": "बिल्कुल नहीं"}),
    "commerce_side": ("आप इनमें से क्या करना पसंद करेंगे?",
                      "आप इनमें से क्या करना पसंद करेंगे? अपना बिज़नेस शुरू करना और चलाना, ध्यान से हिसाब-किताब और टैक्स संभालना, या बाज़ार और अर्थव्यवस्था को समझना?",
                      {"business": "अपना बिज़नेस शुरू करना और चलाना", "accounts": "ध्यान से हिसाब-किताब और टैक्स संभालना",
                       "markets": "बाज़ार और अर्थव्यवस्था को समझना"}),
    "int_arts": ("ड्रॉइंग, डिज़ाइन या चीज़ों को सुंदर बनाना आपको कितना अच्छा लगता है?",
                 "ड्रॉइंग, डिज़ाइन या चीज़ों को सुंदर बनाना आपको कितना अच्छा लगता है? बहुत, थोड़ा, या ज़्यादा नहीं?",
                 {"love": "बहुत", "like": "थोड़ा", "no": "ज़्यादा नहीं"}),
    "arts_side": ("आप सबसे ज़्यादा क्या डिज़ाइन करना चाहेंगे?",
                  "आप सबसे ज़्यादा क्या डिज़ाइन करना चाहेंगे? इमारतें और जगहें, लोगों के इस्तेमाल के ऐप और प्रोडक्ट, या फ़िल्में, फ़ोटो और मीडिया?",
                  {"buildings": "इमारतें और जगहें", "products": "ऐप और प्रोडक्ट जो लोग इस्तेमाल करें",
                   "media": "फ़िल्में, फ़ोटो और मीडिया"}),
    "int_language": ("क्या आपको पढ़ना, लिखना और बोलना अच्छा लगता है — निबंध, डिबेट, कहानियाँ?",
                     "क्या आपको पढ़ना, लिखना और बोलना अच्छा लगता है, जैसे निबंध, डिबेट या कहानियाँ? बहुत, थोड़ा, या ज़्यादा नहीं?",
                     {"love": "बहुत", "like": "थोड़ा", "no": "ज़्यादा नहीं"}),
    "language_side": ("इनमें से आप सबसे ज़्यादा कौन हैं?",
                      "इनमें से आप सबसे ज़्यादा कौन हैं? अपनी बात रखकर डिबेट जीतना, लेख और कहानियाँ लिखना, या दूसरों को चीज़ें समझाना?",
                      {"debate": "अपनी बात रखना, डिबेट जीतना", "writing": "लेख और कहानियाँ लिखना",
                       "teaching": "दूसरों को चीज़ें समझाना"}),
    "int_society": ("क्या आपको इतिहास, राजनीति और देश कैसे चलता है, इसमें रुचि है?",
                    "क्या आपको इतिहास, राजनीति और देश कैसे चलता है, इसमें रुचि है? बहुत, थोड़ी, या ज़्यादा नहीं?",
                    {"love": "बहुत", "like": "थोड़ी", "no": "ज़्यादा नहीं"}),
    "saturday": ("छुट्टी वाले शनिवार को आप क्या चुनेंगे?",
                 "अब थोड़ा आपके बारे में। छुट्टी वाले शनिवार को आप क्या चुनेंगे? कुछ ठीक करना या बनाना, कोई चीज़ कैसे काम करती है ये पढ़ना, कला, संगीत या वीडियो बनाना, दोस्तों के साथ रहना और उनकी मदद करना, या कोई इवेंट आयोजित करना?",
                 {"build": "कुछ ठीक करना या बनाना", "read": "कोई चीज़ कैसे काम करती है, ये पढ़ना",
                  "create": "कला, संगीत या वीडियो बनाना", "friends": "दोस्तों के साथ रहना, उनकी मदद करना",
                  "organise": "कोई इवेंट आयोजित करना या कुछ बेचना"}),
    "group_role": ("ग्रुप प्रोजेक्ट में आप अक्सर क्या करते हैं?",
                   "ग्रुप प्रोजेक्ट में आप अक्सर क्या करते हैं? हाथ से बनाने का काम, रिसर्च, उसे सुंदर बनाना, सबको साथ रखना, टीम को लीड करना, या डेडलाइन और बारीकियों पर नज़र रखना?",
                   {"hands": "हाथ से बनाने का काम", "research": "जवाब ढूँढना, रिसर्च", "design": "उसे सुंदर बनाना",
                    "together": "सबको साथ रखना", "lead": "टीम को लीड करना", "details": "डेडलाइन और बारीकियों पर नज़र"}),
    "compliment": ("कौन सी तारीफ़ सुनकर आपको सबसे ज़्यादा ख़ुशी होगी?",
                   "कौन सी तारीफ़ सुनकर आपको सबसे ज़्यादा ख़ुशी होगी? तुम बहुत प्रैक्टिकल हो, बहुत समझदार हो, बहुत क्रिएटिव हो, बहुत दयालु हो, जन्मजात लीडर हो, या बहुत भरोसेमंद हो?",
                   {"practical": "\"तुम बहुत प्रैक्टिकल हो\"", "smart": "\"तुम बहुत समझदार हो\"",
                    "creative": "\"तुम बहुत क्रिएटिव हो\"", "kind": "\"तुम बहुत दयालु हो\"",
                    "leader": "\"तुम जन्मजात लीडर हो\"", "reliable": "\"तुम बहुत भरोसेमंद हो\""}),
    "people": ("आप पूरे दिन लोगों के साथ काम करना पसंद करेंगे, या ज़्यादातर अकेले?",
               "आप पूरे दिन लोगों के साथ काम करना पसंद करेंगे, दोनों का मिला-जुला, या ज़्यादातर अकेले?",
               {"people": "पूरे दिन लोगों के साथ", "mix": "दोनों का मिला-जुला", "alone": "ज़्यादातर अकेले"}),
    "speaking": ("क्लास के सामने बोलना आपको कैसा लगता है?",
                 "क्लास के सामने बोलना आपको कैसा लगता है? बहुत अच्छा लगता है, ठीक है, या घबराहट होती है?",
                 {"love": "बहुत अच्छा लगता है", "fine": "ठीक है", "nervous": "घबराहट होती है"}),
    "broken": ("घर में कुछ ख़राब हो जाए तो आप क्या करते हैं?",
               "घर में कुछ ख़राब हो जाए तो आप क्या करते हैं? ख़ुद ठीक करने की कोशिश, पता करना कि क्यों ख़राब हुआ, या किसी जानकार को बुलाना?",
               {"fix": "ख़ुद ठीक करने की कोशिश", "why": "पता करना कि क्यों ख़राब हुआ", "call": "किसी जानकार को बुलाना"}),
    "rules": ("साफ़ नियम और स्टेप आपकी मदद करते हैं, या आप अपने तरीके से समझना पसंद करते हैं?",
              "साफ़ नियम और स्टेप आपकी मदद करते हैं, या आप अपने तरीके से समझना पसंद करते हैं?",
              {"rules": "साफ़ नियम और स्टेप मदद करते हैं", "own": "अपना तरीका पसंद है", "both": "काम पर निर्भर करता है"}),
    "workplace": ("आप सबसे ज़्यादा कहाँ काम करना चाहेंगे?",
                  "आप सबसे ज़्यादा कहाँ काम करना चाहेंगे? कंप्यूटर के साथ डेस्क पर, लैब या अस्पताल में, या बाहर फ़ील्ड में?",
                  {"desk": "कंप्यूटर के साथ डेस्क पर", "lab": "लैब या अस्पताल में", "outdoors": "बाहर या फ़ील्ड में"}),
    "adventure": ("क्या आपको घूमने-फिरने, रोमांच और भाग-दौड़ वाला काम अच्छा लगेगा?",
                  "क्या आपको घूमने-फिरने, रोमांच और भाग-दौड़ वाला काम अच्छा लगेगा? बहुत, कभी-कभी, या आप एक तय दिनचर्या पसंद करते हैं?",
                  {"love": "बहुत अच्छा लगेगा", "sometimes": "कभी-कभी", "routine": "तय दिनचर्या पसंद है"}),
    "matters": ("भविष्य की नौकरी में आपके लिए सबसे ज़रूरी क्या है?",
                "भविष्य की नौकरी में आपके लिए सबसे ज़रूरी क्या है? अच्छी कमाई, लोगों की मदद, पक्की नौकरी, क्रिएटिव काम, या इज़्ज़त और नेतृत्व?",
                {"money": "अच्छी कमाई", "helping": "लोगों की मदद", "secure": "पक्की, स्थिर नौकरी",
                 "creative": "क्रिएटिव काम", "respect": "इज़्ज़त और नेतृत्व"}),
    "sector": ("सरकारी नौकरी, प्राइवेट कंपनी, या अपना बिज़नेस?",
               "आप क्या पसंद करेंगे — सरकारी नौकरी, प्राइवेट कंपनी, अपना बिज़नेस, या कोई फ़र्क नहीं पड़ता?",
               {"govt": "सरकारी नौकरी", "private": "प्राइवेट कंपनी", "own": "अपना बिज़नेस", "any": "कोई फ़र्क नहीं पड़ता"}),
    "years": ("बारहवीं के बाद आप कितने साल पढ़ाई करने को तैयार हैं?",
              "बारहवीं के बाद आप कितने साल पढ़ाई करने को तैयार हैं? तीन-चार साल, पाँच-छह साल, या जितना लगे?",
              {"short": "3–4 साल", "medium": "5–6 साल", "long": "जितना लगे"}),
    "pressure": ("आप मुक़ाबले और दबाव, जैसे बड़ी परीक्षाओं को कैसे संभालते हैं?",
                 "आख़िरी सवाल। आप मुक़ाबले और दबाव को, जैसे बड़ी एंट्रेंस परीक्षाओं को, कैसे संभालते हैं? इससे जोश आता है, ठीक है, या तनाव होता है?",
                 {"thrive": "इससे जोश आता है", "fine": "ठीक है", "stress": "तनाव होता है"}),
}

# What a student might say in Hinglish (Roman) and Hindi (Devanagari), per option.
LIKERT = {
    "love": (["bahut pasand", "bahut accha", "bahut achha", "pyaar", "favourite", "favorite", "bahut", "zabardast"],
             ["बहुत पसंद", "बहुत अच्छा", "बहुत"]),
    "like": (["pasand hai", "accha lagta", "achha lagta", "theek", "thik", "thoda", "thoda bahut"],
             ["पसंद है", "अच्छा लगता", "ठीक", "थोड़ा"]),
    "meh": (["zyada nahi", "jyada nahi", "nahi pasand", "pasand nahi", "boring", "khaas nahi"],
            ["ज़्यादा नहीं", "ज्यादा नहीं", "पसंद नहीं", "बोरिंग"]),
    "hard": (["mushkil", "kamzor", "samajh nahi aata", "dikkat", "tough"],
             ["मुश्किल", "कमज़ोर", "कमजोर", "समझ नहीं आता"]),
    "no": (["bilkul nahi", "zyada nahi", "nahi", "boring"], ["बिल्कुल नहीं", "ज़्यादा नहीं", "नहीं"]),
}
LIKERT_ITEMS = {"int_maths", "int_physics", "int_chemistry", "int_biology", "int_computer", "int_commerce",
                "int_arts", "int_language", "int_society"}
EXTRA = {  # (item, option): (hinglish, hindi)
    ("int_computer", "never"): (["kabhi nahi", "try nahi", "nahi kiya"], ["कभी नहीं", "आज़माया नहीं"]),
    ("build_things", "yes"): (["haan", "han", "bilkul", "zaroor"], ["हाँ", "बिल्कुल", "ज़रूर"]),
    ("build_things", "maybe"): (["shayad", "kabhi kabhi"], ["शायद", "कभी-कभी"]),
    ("build_things", "no"): (["nahi", "zyada nahi"], ["नहीं"]),
    ("hospital", "fine"): (["koi dikkat nahi", "theek hai", "bilkul theek", "darr nahi"], ["कोई दिक्कत नहीं", "बिल्कुल ठीक"]),
    ("hospital", "okay"): (["thoda", "chal jayega"], ["थोड़ा", "चल जाएगा"]),
    ("hospital", "avoid"): (["darr", "dar lagta", "door rehna", "nahi"], ["डर", "दूर रहना", "नहीं"]),
    ("people", "people"): (["logon ke saath", "sabke saath"], ["लोगों के साथ"]),
    ("people", "mix"): (["dono", "mix"], ["दोनों"]),
    ("people", "alone"): (["akele", "khud"], ["अकेले"]),
    ("speaking", "love"): (["bahut accha", "maza aata"], ["बहुत अच्छा", "मज़ा"]),
    ("speaking", "fine"): (["theek", "thik"], ["ठीक"]),
    ("speaking", "nervous"): (["ghabrahat", "darr", "dar lagta", "sharm"], ["घबराहट", "डर"]),
    ("broken", "fix"): (["khud theek", "khud thik", "khud"], ["ख़ुद", "खुद"]),
    ("broken", "why"): (["pata karna", "kyun", "search"], ["क्यों", "पता"]),
    ("broken", "call"): (["bulana", "papa", "mummy", "mechanic"], ["बुला", "पापा", "मम्मी"]),
    ("rules", "rules"): (["niyam", "steps", "rules"], ["नियम"]),
    ("rules", "own"): (["apne tarike", "apna tarika"], ["अपने तरीके", "अपना तरीका"]),
    ("rules", "both"): (["depend", "dono"], ["निर्भर", "दोनों"]),
    ("workplace", "outdoors"): (["bahar", "field"], ["बाहर", "फ़ील्ड"]),
    ("workplace", "lab"): (["lab", "hospital", "aspatal"], ["लैब", "अस्पताल"]),
    ("adventure", "love"): (["bahut accha", "haan"], ["बहुत अच्छा", "हाँ"]),
    ("adventure", "sometimes"): (["kabhi kabhi", "shayad"], ["कभी-कभी", "शायद"]),
    ("adventure", "routine"): (["routine", "tay", "nahi"], ["दिनचर्या", "नहीं"]),
    ("matters", "money"): (["paisa", "kamai", "salary"], ["पैसा", "कमाई"]),
    ("matters", "helping"): (["madad", "logon ki madad", "seva"], ["मदद", "सेवा"]),
    ("matters", "secure"): (["pakki naukri", "stable", "surakshit"], ["पक्की", "स्थिर"]),
    ("matters", "creative"): (["creative", "kuch naya"], ["क्रिएटिव"]),
    ("matters", "respect"): (["izzat", "respect", "naam"], ["इज़्ज़त", "इज्जत", "नेतृत्व"]),
    ("sector", "govt"): (["sarkari", "government"], ["सरकारी"]),
    ("sector", "private"): (["private", "company"], ["प्राइवेट", "कंपनी"]),
    ("sector", "own"): (["apna business", "khud ka"], ["अपना बिज़नेस", "अपना"]),
    ("sector", "any"): (["farak nahi", "fark nahi", "kuch bhi", "pata nahi"], ["फ़र्क नहीं", "फर्क नहीं", "कुछ भी"]),
    ("years", "short"): (["teen", "char", "chaar", "kam"], ["तीन", "चार"]),
    ("years", "medium"): (["paanch", "panch", "chhe", "chhah"], ["पाँच", "पांच", "छह"]),
    ("years", "long"): (["jitna lage", "jitna bhi"], ["जितना लगे", "जितना"]),
    ("pressure", "thrive"): (["josh", "maza", "motivation"], ["जोश", "मज़ा"]),
    ("pressure", "fine"): (["theek", "thik", "manage"], ["ठीक"]),
    ("pressure", "stress"): (["tension", "stress", "tanav", "darr"], ["तनाव", "टेंशन", "डर"]),
    ("int_commerce", "love"): (["bahut", "bahut interesting"], ["बहुत"]),
    ("int_commerce", "like"): (["thoda"], ["थोड़ा"]),
}

DIMENSIONS = {
    # what the student enjoys
    "maths": ("maths", "मैथ्स", "subject"), "physics": ("physics", "फ़िज़िक्स", "subject"),
    "chemistry": ("chemistry", "केमिस्ट्री", "subject"), "biology": ("biology", "बायोलॉजी", "subject"),
    "computer": ("computers and coding", "कंप्यूटर और कोडिंग", "subject"),
    "commerce": ("business and money", "बिज़नेस और पैसा", "subject"),
    "arts": ("drawing and design", "ड्रॉइंग और डिज़ाइन", "subject"),
    "language": ("reading, writing and speaking", "पढ़ना, लिखना और बोलना", "subject"),
    "society": ("history and how the country runs", "इतिहास और देश कैसे चलता है", "subject"),
    "tech": ("technology", "टेक्नोलॉजी", "subject"),
    # the kind of person they are (Holland's RIASEC)
    "realistic": ("hands-on building and fixing", "हाथ से बनाना और ठीक करना", "riasec"),
    "investigative": ("figuring out how things work", "चीज़ें कैसे काम करती हैं, ये समझना", "riasec"),
    "artistic": ("creativity", "रचनात्मकता", "riasec"),
    "social": ("helping people", "लोगों की मदद", "riasec"),
    "enterprising": ("leading and persuading", "नेतृत्व और लोगों को मनाना", "riasec"),
    "conventional": ("careful, organised work", "ध्यान से, व्यवस्थित काम", "riasec"),
    # how they'd like to work
    "communication": ("talking with people", "लोगों से बात करना", "work_style"),
    "outdoor": ("active, on-site work", "भाग-दौड़ वाला, फ़ील्ड का काम", "work_style"),
    "clinical": ("diagnosing and treating patients", "मरीज़ों का इलाज", "work_style"),
    "caregiving": ("caring for patients", "मरीज़ों की देखभाल", "work_style"),
    # what matters to them
    "blood_ok": ("comfort with hospitals and blood", "अस्पताल और खून से सहजता", "values"),
    "long_study": ("readiness for a long study path", "लंबी पढ़ाई के लिए तैयारी", "values"),
    "stability": ("a secure job", "पक्की नौकरी", "values"),
    "money": ("earning well", "अच्छी कमाई", "values"),
    # how they learn (for the roadmap, Phase 5)
    "learning:watching": ("learning by watching", "देखकर सीखना", "learning"),
    "learning:reading": ("learning by reading", "पढ़कर सीखना", "learning"),
    "learning:doing": ("learning by doing", "करके सीखना", "learning"),
    "learning:discussing": ("learning by discussing", "चर्चा करके सीखना", "learning"),
    "learning:solo": ("studying alone", "अकेले पढ़ना", "learning"),
    "learning:group": ("studying with others", "दूसरों के साथ पढ़ना", "learning"),
    "learning:morning": ("studying in the morning", "सुबह पढ़ना", "learning"),
    "learning:evening": ("studying in the evening", "शाम को पढ़ना", "learning"),
    "learning:night": ("studying late at night", "देर रात पढ़ना", "learning"),
}


def text(en, hi):
    return {"en": en, "hi": hi}


def learning_items():
    section = text("How you learn", "आप कैसे सीखते हैं")

    def option(key, en, hi, weights, hinglish, hindi):
        return {"key": key, "label": text(en, hi), "weights": weights,
                "keywords": {"en": [], "hinglish": hinglish, "hi": hindi}}

    return [
        {"key": "learn_how", "type": "choice", "section": section,
         "prompt": text("When you learn something new, what helps most?",
                        "कुछ नया सीखते समय आपकी सबसे ज़्यादा मदद किससे होती है?"),
         "speak": text("A few questions on how you learn. When you learn something new, what helps most? Watching a video, "
                       "reading about it, trying it yourself, or talking it through with someone?",
                       "अब कुछ सवाल कि आप कैसे सीखते हैं। कुछ नया सीखते समय सबसे ज़्यादा मदद किससे होती है? वीडियो देखकर, "
                       "पढ़कर, ख़ुद करके, या किसी से बात करके?"),
         "options": [
             option("watch", "Watching a video", "वीडियो देखकर", {"learning:watching": 3}, ["video", "dekh"], ["वीडियो", "देख"]),
             option("read", "Reading about it", "पढ़कर", {"learning:reading": 3}, ["padh", "kitab"], ["पढ़", "किताब"]),
             option("do", "Trying it myself", "ख़ुद करके", {"learning:doing": 3}, ["khud", "karke"], ["ख़ुद", "खुद", "करके"]),
             option("talk", "Talking it through with someone", "किसी से बात करके", {"learning:discussing": 3},
                    ["baat", "discuss", "pooch"], ["बात", "चर्चा"]),
         ]},
        {"key": "learn_with", "type": "choice", "section": section,
         "prompt": text("Do you study better alone or with friends?", "आप अकेले बेहतर पढ़ते हैं या दोस्तों के साथ?"),
         "speak": text("Do you study better alone, with friends, or a mix?",
                       "आप अकेले बेहतर पढ़ते हैं, दोस्तों के साथ, या दोनों तरह?"),
         "options": [
             option("alone", "Alone", "अकेले", {"learning:solo": 3}, ["akele", "khud"], ["अकेले"]),
             option("friends", "With friends", "दोस्तों के साथ", {"learning:group": 3}, ["dost", "friends", "saath"], ["दोस्त", "साथ"]),
             option("mix", "A mix", "दोनों तरह", {"learning:solo": 1.5, "learning:group": 1.5}, ["dono", "mix"], ["दोनों"]),
         ]},
        {"key": "learn_when", "type": "choice", "section": section,
         "prompt": text("When do you concentrate best?", "आपका ध्यान सबसे अच्छा कब लगता है?"),
         "speak": text("When do you concentrate best? Morning, evening, or late at night?",
                       "आपका ध्यान सबसे अच्छा कब लगता है? सुबह, शाम, या देर रात?"),
         "options": [
             option("morning", "Morning", "सुबह", {"learning:morning": 3}, ["subah", "savere"], ["सुबह"]),
             option("evening", "Evening", "शाम", {"learning:evening": 3}, ["shaam", "sham"], ["शाम"]),
             option("night", "Late at night", "देर रात", {"learning:night": 3}, ["raat", "der raat"], ["रात"]),
         ]},
    ]


def port(question):
    prompt_hi, speak_hi, labels_hi = HI[question["id"]]
    options = []
    for option in question["options"]:
        hinglish, hindi = [], []
        if question["id"] in LIKERT_ITEMS and option["id"] in LIKERT:
            hinglish, hindi = LIKERT[option["id"]]
        extra = EXTRA.get((question["id"], option["id"]))
        if extra:
            hinglish, hindi = extra[0] + [w for w in hinglish if w not in extra[0]], extra[1] + [w for w in hindi if w not in extra[1]]
        options.append({"key": option["id"], "label": text(option["label"], labels_hi[option["id"]]),
                        "weights": option["weights"],
                        "keywords": {"en": option.get("keywords", []), "hinglish": hinglish, "hi": hindi}})
    item = {"key": question["id"], "type": "choice",
            "section": text(question["section"], SECTIONS[question["section"]]),
            "prompt": text(question["text"], prompt_hi), "speak": text(question["speak"], speak_hi), "options": options}
    if question.get("requires"):
        item["requires"] = question["requires"]
    return item


def build():
    items = [port(q) for q in OLD["questions"]]
    # "How you learn" goes before the closing "What matters" questions, so "Last one" stays last.
    at = next(n for n, i in enumerate(items) if i["key"] == "matters")
    items[at:at] = learning_items()
    return {
        "key": "interests", "version": 1, "category": "interest",
        "title": text("What you enjoy", "आपको क्या पसंद है"),
        "about": text("Subjects, the kind of person you are, how you like to work and learn, and what matters to you. "
                      "There are no right or wrong answers.",
                      "विषय, आप किस तरह के इंसान हैं, आप कैसे काम करना और सीखना पसंद करते हैं, और आपके लिए क्या ज़रूरी है। "
                      "कोई जवाब सही या ग़लत नहीं है।"),
        "intro": text("Let's find out what you enjoy. I'll ask about thirty quick questions — there are no right or wrong "
                      "answers, so just answer naturally, or tap.",
                      "चलिए पता करते हैं कि आपको क्या पसंद है। मैं लगभग तीस छोटे सवाल पूछूँगी — कोई जवाब सही या ग़लत नहीं है, "
                      "बस जैसा लगे वैसा बताइए, या टैप कीजिए।"),
        "scoring_method": "weighted_options", "est_minutes": 6,
        "dimensions": {k: {"en": en, "hi": hi, "group": group} for k, (en, hi, group) in DIMENSIONS.items()},
        "items": items,
    }


if __name__ == "__main__":
    OUT.write_text(json.dumps(build(), ensure_ascii=False, indent=1) + "\n")
    print(f"wrote {OUT.relative_to(ROOT)}")
