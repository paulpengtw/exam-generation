

 user is setting up a workspace for the exam generation; the following custom instructions and prompts are proof-of-concept worked from Claude Desktop approved by supervisors, assistant now will come up with a implementation list for actual working CLI-based POC project to directly output exam text or images(e.g. charts)
 
 
"""custom-instructions
 Assistant will now come up with exam question target for 7年級, 8年級, and 9年級's students (which is "第四學習階段");
the output of the exam questions will be like this
```
{
  "情境": [
    "個人",
    "社會時事",
    "科學",
    "職業",
    "建築與藝術",
    "數學文字情境"
  ],
  "題型種類": [
    "單一題",
    "題組題"
  ],
  "題型": [
    "選擇題",
    "是非題",
    "封閉式建構反應題",
    "開放式建構反應題"
  ],
  "數學思考": [
    "形成",
    "運用",
    "詮釋評估"
  ],
  "學習內容": [
    "",
    ""
  ],
  "題目":[

  ],
  "正確解題分析":[
    
  ]
}
```
;
assistant will choose fill   "學習內容" objects based on `學習內容.json`, single exam question could include multiple "學習內容" objects; on "情境", "題型種類", "題型" can only choose one object;  "數學思考" could up to three;
assistant will learn about 國小 and 高中's 學習內容, in order to ensure 7年級, 8年級, and 9年級's students are capable to answer the exam question but also keep the question challenging enough for 7年級, 8年級, and 9年級's students
;
`112P_Math.pdf`, `113P_Math.pdf`, `114P_Math.pdf` are example exam question sets for assistant to refer.
"""
"""prompts-Random-questions-with-charts
assistant now will randomly come up single question  include chart/charts but would NOT replicate questions wrote in this Projects
"""
"""assistant-answer-for-Random-questions-with-charts
Now let me look at an example exam to understand the question style:Now I have context on the curriculum, learning stages, and the previous question in this project (which was a text-only 畢氏定理 + 一元二次方程式 question). Let me design a new chart-based question.Now let me create the chart-based exam question. I'll build a React artifact with the histogram and present the complete question.Here's the structured output and the interactive artifact above (click "顯示解析" for the full solution):

```json
{
  "情境": "社會時事",
  "題型種類": "單一題",
  "題型": "選擇題",
  "數學思考": [
    "運用",
    "詮釋評估"
  ],
  "學習內容": [
    "D-7-1：統計圖表：蒐集生活中常見的數據資料，整理並繪製成含有原始資料或百分率的統計圖表：直方圖、長條圖、圓形圖、折線圖、列聯表。",
    "D-7-2：統計數據：用平均數、中位數與眾數描述一組資料的特性。",
    "D-8-1：統計資料處理：累積次數、相對次數、累積相對次數折線圖。"
  ],
  "題目": [
    "某國中針對全校 200 名學生進行「每日使用手機時間」的問卷調查，將調查結果整理成直方圖（見圖）。各區間人數為：0~30 分鐘 15 人、30~60 分鐘 35 人、60~90 分鐘 55 人、90~120 分鐘 50 人、120~150 分鐘 30 人、150~180 分鐘 15 人。",
    "根據上圖，下列哪一個敘述是正確的？",
    "(A) 中位數落在 90～120 分鐘的區間內",
    "(B) 眾數所在的組別為 60～90 分鐘，且中位數也落在此區間內",
    "(C) 每日使用手機超過 90 分鐘的學生占全校的一半以上",
    "(D) 120～150 分鐘此組的相對次數為 20%"
  ],
  "正確解題分析": [
    "正確答案：(B)",
    "【步驟一：辨識眾數所在組別】直方圖各組人數：0~30→15、30~60→35、60~90→55、90~120→50、120~150→30、150~180→15。人數最多的組別為 60~90 分鐘（55人），即眾數所在組別。",
    "【步驟二：以累積次數判斷中位數】全校 200 人，中位數為第 100 與第 101 筆的平均。累積次數：0~30→15、0~60→50、0~90→105。第 100 筆數據落在 60~90 的區間（累積至 60 分鐘僅 50 人，至 90 分鐘已達 105 人），故中位數在 60~90 分鐘區間。",
    "【步驟三：逐項驗證】(A) ✗ 中位數在 60~90 而非 90~120；(B) ✓ 眾數組別 60~90，中位數亦在此區間；(C) ✗ 超過 90 分鐘共 50+30+15=95 人，占 47.5%，不到一半；(D) ✗ 120~150 有 30 人，相對次數 30/200=15%，非 20%。",
    "【先備知識確認】本題需具備國小折線圖與長條圖的報讀經驗（D-5-1），7年級統計圖表判讀（D-7-1）與平均數、中位數、眾數概念（D-7-2），以及 8年級累積次數與相對次數（D-8-1）。不涉及高中進階統計（如 D-10-1 信賴區間），屬第四學習階段可獨立作答範圍。四個選項分別測試累積次數誤判、綜合判讀、比例計算、相對次數計算等常見盲點，具有鑑別度。"
  ]
}
```

**設計說明：**

這題以「手機使用時間」的社會議題為情境，搭配直方圖讓學生進行統計圖表的判讀與推理。核心考點有三：從直方圖辨識眾數所在組別、透過累積次數定位中位數所在區間、以及相對次數的計算。四個選項分別瞄準不同的常見錯誤路徑 — (A) 混淆累積次數的順序、(C) 粗略估算比例而忽略精確計算、(D) 分母取錯導致相對次數錯誤 — 具有良好的誘答與鑑別功能。
"""
"""prompts-Random-question-generation-with-images
assistant now will randomly come up `INPUT-DIGITS` question  include image/images but would NOT replicate questions wrote in this Projects
"""
"""assistant-answer-for-Random-question-generation-with-images
[
  {
    "題號": "Q2",
    "情境": "社會時事",
    "題型種類": "單一題",
    "題型": "選擇題",
    "數學思考": [
      "詮釋評估"
    ],
    "學習內容": [
      {
        "編碼": "D-9-1",
        "說明": "統計數據的分布：全距；四分位距；盒狀圖。"
      },
      {
        "編碼": "D-7-2",
        "說明": "統計數據：用平均數、中位數與眾數描述一組資料的特性。"
      }
    ],
    "圖片": "q1_boxplot.png",
    "題目": [
      "某校段考後，老師將甲班與乙班的數學成績分別繪製成盒狀圖，如圖所示。",
      "已知甲班的五數摘要為：最小值 40、Q₁ = 55、中位數 = 70、Q₃ = 80、最大值 95；",
      "乙班的五數摘要為：最小值 35、Q₁ = 58、中位數 = 72、Q₃ = 88、最大值 100。",
      "",
      "根據此盒狀圖，下列敘述何者正確？",
      "",
      "(A) 甲班的全距大於乙班的全距",
      "(B) 甲班的四分位距大於乙班的四分位距",
      "(C) 乙班成績的中間 50% 分布範圍比甲班大",
      "(D) 甲班至少有一半的學生成績在 75 分以上"
    ],
    "正確答案": "(C)",
    "正確解題分析": [
      "【逐項分析】",
      "",
      "(A) 甲班全距 = 95 − 40 = 55；乙班全距 = 100 − 35 = 65。",
      "   甲班全距 (55) < 乙班全距 (65)，故 (A) 錯誤。",
      "",
      "(B) 甲班四分位距 (IQR) = Q₃ − Q₁ = 80 − 55 = 25；",
      "   乙班四分位距 (IQR) = Q₃ − Q₁ = 88 − 58 = 30。",
      "   甲班 IQR (25) < 乙班 IQR (30)，故 (B) 錯誤。",
      "",
      "(C) 盒狀圖中「箱子」的寬度代表中間 50% 數據的分布範圍，即四分位距。",
      "   乙班 IQR = 30 > 甲班 IQR = 25，",
      "   因此乙班中間 50% 的分布範圍確實比甲班大，(C) 正確。",
      "",
      "(D) 甲班中位數 = 70，表示至少有一半學生成績 ≥ 70 分，",
      "   但無法保證有一半學生成績 ≥ 75 分，故 (D) 錯誤。",
      "",
      "正確答案為 (C)。"
    ]
  },
  {
    "題號": "Q3",
    "情境": "個人",
    "題型種類": "單一題",
    "題型": "封閉式建構反應題",
    "數學思考": [
      "形成",
      "運用"
    ],
    "學習內容": [
      {
        "編碼": "S-9-2",
        "說明": "三角形的相似性質：三角形的相似判定（AA、SAS、SSS）；對應邊長之比＝對應高之比。"
      },
      {
        "編碼": "N-7-9",
        "說明": "比與比例式：比；比例式；正比；反比；相關之基本運算與應用問題。"
      }
    ],
    "圖片": "q2_shadow.png",
    "題目": [
      "小明晚上在路燈下散步。如圖所示，路燈高度為 6 公尺，小明身高為 1.6 公尺，小明站在距離路燈底部 4 公尺的位置。假設路燈的光線從燈頂射出，地面為水平面，路燈與小明皆垂直於地面。",
      "",
      "請問：小明的影子長度為多少公尺？",
      "（請寫出完整計算過程，答案若為分數請化為最簡分數。）"
    ],
    "正確答案": "16/11 公尺（即 1 又 5/11 公尺）",
    "正確解題分析": [
      "【步驟 1：建立相似三角形模型】",
      "設路燈底部為 O，燈頂為 L（OL = 6 m）。",
      "小明腳底為 P（OP = 4 m），頭頂為 H（PH = 1.6 m）。",
      "影子尖端為 S（在地面上），影子長度 PS = x。",
      "",
      "由光線路徑形成兩個三角形：",
      "・大三角形 △LOS：高 = 6，底 = OS = 4 + x",
      "・小三角形 △HPS：高 = 1.6，底 = PS = x",
      "",
      "路燈與小明都垂直地面 → ∠L = ∠H = 90°（相對地面），",
      "且兩三角形共享影子尖端 S 處的角，",
      "由 AA 相似判定：△LOS ~ △HPS。",
      "",
      "【步驟 2：列出比例式】",
      "對應邊成比例：",
      "  6 / (4 + x) = 1.6 / x",
      "",
      "【步驟 3：交叉相乘解方程式】",
      "  6x = 1.6 × (4 + x)",
      "  6x = 6.4 + 1.6x",
      "  6x − 1.6x = 6.4",
      "  4.4x = 6.4",
      "  x = 6.4 ÷ 4.4 = 64/44 = 16/11",
      "",
      "【步驟 4：驗算】",
      "  OS = 4 + 16/11 = 60/11",
      "  6 ÷ (60/11) = 6 × 11/60 = 66/60 = 11/10",
      "  1.6 ÷ (16/11) = 1.6 × 11/16 = 17.6/16 = 11/10 ✓",
      "",
      "答案：影子長度為 16/11 公尺（≈ 1.45 公尺）。"
    ]
  },
  {
    "題號": "Q4",
    "情境": "個人",
    "題型種類": "單一題",
    "題型": "選擇題",
    "數學思考": [
      "詮釋評估",
      "運用"
    ],
    "學習內容": [
      {
        "編碼": "F-8-1",
        "說明": "一次函數：透過對應關係認識函數、常數函數（y=c）、一次函數（y=ax+b）。"
      },
      {
        "編碼": "F-8-2",
        "說明": "一次函數的圖形：常數函數的圖形；一次函數的圖形。"
      }
    ],
    "圖片": "q3_linear.png",
    "題目": [
      "社區水塔進行定期清洗排水，排水過程中水量與時間的關係如圖所示，其函數關係式為 y = −3x + 60（其中 x 為排水時間，單位：分鐘；y 為水塔中的水量，單位：公升）。",
      "",
      "根據圖形及函數關係式，下列敘述何者錯誤？",
      "",
      "(A) 排水前水塔中有 60 公升的水",
      "(B) 每分鐘排出 3 公升的水",
      "(C) 排水 8 分鐘後，水塔中剩餘 36 公升的水",
      "(D) 排水 15 分鐘後，水塔中剩餘 20 公升的水"
    ],
    "正確答案": "(D)",
    "正確解題分析": [
      "【逐項驗證】",
      "",
      "(A) 當 x = 0 時，y = −3(0) + 60 = 60。",
      "   排水前確實有 60 公升，(A) 正確。",
      "",
      "(B) 斜率 = −3，代表每經過 1 分鐘水量減少 3 公升，",
      "   即每分鐘排出 3 公升，(B) 正確。",
      "",
      "(C) 當 x = 8 時，y = −3(8) + 60 = −24 + 60 = 36。",
      "   剩餘 36 公升，(C) 正確。",
      "",
      "(D) 當 x = 15 時，y = −3(15) + 60 = −45 + 60 = 15。",
      "   排水 15 分鐘後剩餘 15 公升，而非選項所述的 20 公升。",
      "   (D) 錯誤。",
      "",
      "正確答案（錯誤的選項）為 (D)。"
    ]
  },
  {
    "題號": "Q5",
    "情境": "數學文字情境",
    "題型種類": "單一題",
    "題型": "選擇題",
    "數學思考": [
      "形成",
      "運用"
    ],
    "學習內容": [
      {
        "編碼": "D-9-3",
        "說明": "古典機率：具有對稱性的情境下（銅板、骰子、撲克牌、抽球等）之機率。"
      },
      {
        "編碼": "D-9-2",
        "說明": "認識機率：機率的意義；樹狀圖（以兩層為限）。"
      }
    ],
    "圖片": "q4_spinner.png",
    "題目": [
      "如圖所示的轉盤，分為四個顏色區域：紅色區域的圓心角為 120°、藍色區域為 60°、黃色區域為 60°、綠色區域為 120°。小華連續轉了此轉盤兩次，每次轉動後指針停在各區域的機率與該區域的圓心角大小成正比。",
      "",
      "請問：兩次都轉到相同顏色的機率為何？",
      "",
      "(A) 1/4",
      "(B) 11/36",
      "(C) 5/18",
      "(D) 1/3"
    ],
    "正確答案": "(C)",
    "正確解題分析": [
      "【步驟 1：計算各區域被選中的機率】",
      "全部圓心角合計 = 120° + 60° + 60° + 120° = 360°。",
      "  P(紅) = 120/360 = 1/3",
      "  P(藍) = 60/360 = 1/6",
      "  P(黃) = 60/360 = 1/6",
      "  P(綠) = 120/360 = 1/3",
      "",
      "【步驟 2：列出「兩次同色」的所有情形】",
      "兩次為獨立事件，兩次都轉到同一顏色的機率 =",
      "  P(紅,紅) + P(藍,藍) + P(黃,黃) + P(綠,綠)",
      "= (1/3)² + (1/6)² + (1/6)² + (1/3)²",
      "= 1/9 + 1/36 + 1/36 + 1/9",
      "",
      "【步驟 3：通分計算】",
      "最小公分母為 36：",
      "= 4/36 + 1/36 + 1/36 + 4/36",
      "= 10/36",
      "= 5/18",
      "",
      "正確答案為 (C) 5/18。",
      "",
      "【錯誤選項分析】",
      "(A) 1/4 = 9/36：若誤以為四色機率均等（各 1/4），則 4×(1/4)² = 4/16 = 1/4。",
      "(B) 11/36：可能因計算過程中加法出錯。",
      "(D) 1/3：可能只算了 P(紅,紅)+P(綠,綠) = 2/9 ≈ 0.22，再湊整為 1/3。"
    ]
  }
]
"""
"""prompts-Random-question-format
assistant now will randomly come up `INPUT-DIGITS` more questions which won't include charts or images, but would NOT replicate questions wrote in this Projects, if all 學習內容 from 7 to 9 grades had exhausted, assistant will integrate multiple different 學習內容 to come up with new questions.
"""
"""assistant-answer-for-Random-question-format
Good — let me first verify no prior questions exist in the project, then design 4 new diverse questions.No prior exam questions found in the project knowledge. Combined with the question already generated in this conversation (which used S-8-6 + A-8-7), I'll now create 4 new questions spanning different 學習內容, 情境, 題型, and grade levels.

---

**【題目一】**

```json
{
  "情境": "社會時事",
  "題型種類": "單一題",
  "題型": "選擇題",
  "數學思考": [
    "形成",
    "運用"
  ],
  "學習內容": [
    "N-7-9：比與比例式：比；比例式；正比；反比；相關之基本運算與應用問題，教學情境應以有意義之比值為例。",
    "D-7-2：統計數據：用平均數、中位數與眾數描述一組資料的特性；使用計算機的「M+」或「Σ」鍵計算平均數。"
  ],
  "題目": [
    "某市政府針對市民通勤方式進行調查，共調查 200 人，其中偏好公車、捷運、自行車三種交通方式的人數比為 2：5：3。調查同時統計了這三類通勤者的平均每日通勤時間，分別為 65 分鐘、80 分鐘、70 分鐘。若以各類人數做為加權，則這 200 位受訪者的加權平均每日通勤時間為多少分鐘？",
    "(A) 71.67",
    "(B) 74",
    "(C) 75",
    "(D) 80"
  ],
  "正確解題分析": [
    "正確答案：(B)",
    "【步驟一：由比例求各組人數】人數比 2：5：3，總和 2+5+3=10 份，總人數 200 人。公車組 = 200×(2/10)= 40 人；捷運組 = 200×(5/10)= 100 人；自行車組 = 200×(3/10)= 60 人。",
    "【步驟二：計算加權平均】加權平均 = (40×65 + 100×80 + 60×70) ÷ 200 = (2600 + 8000 + 4200) ÷ 200 = 14800 ÷ 200 = 74 分鐘。",
    "【錯誤選項分析】(A) 71.67：誤將三組平均值直接取算術平均 (65+80+70)÷3 ≈ 71.67，忽略各組人數不同；(C) 75：可能在計算加權時將比例 2:5:3 誤記為 2:4:4 或運算過程中四捨五入錯誤；(D) 80：僅取最多人數組（捷運組）的平均值。",
    "【先備知識確認】本題需要國小階段的乘法與除法計算能力，以及 7 年級的比與比例式（N-7-9）來分配各組人數，並結合統計數據中加權平均數的概念（D-7-2）。不涉及高中統計方法。"
  ]
}
```

---

**【題目二】**

```json
{
  "情境": "個人",
  "題型種類": "單一題",
  "題型": "封閉式建構反應題",
  "數學思考": [
    "形成",
    "運用",
    "詮釋評估"
  ],
  "學習內容": [
    "N-8-4：等差數列：等差數列；給定首項、公差計算等差數列的一般項。",
    "N-8-5：等差級數求和：等差級數求和公式；生活中相關的問題。"
  ],
  "題目": [
    "小華為了準備畢業旅行的旅費，從某天開始每天存錢到撲滿中。他第一天存了 10 元，之後每天比前一天多存 3 元（即第二天存 13 元、第三天存 16 元……以此類推）。",
    "(1) 請寫出小華第 20 天存入的金額。",
    "(2) 請計算小華在前 20 天內總共存了多少元。"
  ],
  "正確解題分析": [
    "正確答案：(1) 67 元；(2) 770 元",
    "【(1) 求第 20 天存入金額】此為等差數列，首項 a₁ = 10，公差 d = 3。一般項公式：aₙ = a₁ + (n−1)d。a₂₀ = 10 + (20−1)×3 = 10 + 57 = 67 元。",
    "【(2) 求前 20 天總額】等差級數求和公式：Sₙ = n×(a₁ + aₙ) ÷ 2。S₂₀ = 20×(10 + 67) ÷ 2 = 20×77 ÷ 2 = 770 元。",
    "【常見錯誤】(1) 誤用 n=20 代入 a₁+n×d = 10+60 = 70，忘記一般項公式中應為 (n−1)；(2) 求和時忘記除以 2，得到 1540；或誤將項數代為 19。",
    "【詮釋評估面向】學生應能判斷此存錢模式確實構成等差數列（每天增加固定金額），並在算出結果後能回頭檢驗：第 1 天 10 元到第 20 天 67 元，平均每天約 38.5 元，20 天共約 770 元，合理。",
    "【先備知識確認】需要國小階段的整數四則運算能力，以及 8 年級的等差數列一般項公式（N-8-4）與等差級數求和（N-8-5）。不涉及等比數列或高中數列求和概念。"
  ]
}
```

---

**【題目三】**

```json
{
  "情境": "職業",
  "題型種類": "單一題",
  "題型": "選擇題",
  "數學思考": [
    "形成",
    "運用"
  ],
  "學習內容": [
    "S-9-2：三角形的相似性質：三角形的相似判定（AA、SAS、SSS）；對應邊長之比＝對應高之比；對應面積之比＝對應邊長平方之比；利用三角形相似的概念解應用問題。",
    "S-9-4：相似直角三角形邊長比值的不變性：直角三角形中某一銳角的角度決定邊長比值，該比值為不變量；三內角為 30°、60°、90° 其邊長比為 1：√3：2。"
  ],
  "題目": [
    "一位測量工程師想測量一條河流的寬度。他站在河岸上的 A 點，正對面河岸的 B 點使得 AB 垂直於河岸。他沿著河岸從 A 點向右走 20 公尺到達 C 點，測得 ∠BCA = 60°。已知在直角三角形中，若一銳角為 60°，則其對邊與鄰邊的長度比為 √3：1。請問河流寬度 AB 為多少公尺？",
    "(A) 10√3",
    "(B) 20√3",
    "(C) 20",
    "(D) 40"
  ],
  "正確解題分析": [
    "正確答案：(B)",
    "【步驟一：辨識直角三角形】△ABC 中，∠BAC = 90°（AB 垂直河岸），∠BCA = 60°，故 ∠ABC = 30°。",
    "【步驟二：利用邊長比值】在此直角三角形中，60° 角（∠BCA）的對邊為 AB，鄰邊為 AC = 20 公尺。由題意所給比值，對邊：鄰邊 = √3：1，故 AB：AC = √3：1。",
    "【步驟三：求 AB】AB = AC × √3 = 20√3 公尺。",
    "【錯誤選項分析】(A) 10√3：可能誤將 AC 當作斜邊，使用 30-60-90 三角形的斜邊比關係得到 AC÷2×√3 = 10√3；(C) 20：直接將 AC 的長度當作 AB；(D) 40：誤將 AC 當作短邊乘以 2。",
    "【先備知識確認】需要國小階段對直角的認識，8 年級的畢氏定理概念做背景理解，以及 9 年級的三角形相似性質（S-9-2）與相似直角三角形邊長比值的不變性（S-9-4）。不涉及高中正弦、餘弦等三角函數定義。"
  ]
}
```

---

**【題目四】**

```json
{
  "情境": "數學文字情境",
  "題型種類": "單一題",
  "題型": "選擇題",
  "數學思考": [
    "運用"
  ],
  "學習內容": [
    "A-8-1：二次式的乘法公式：(a+b)(a-b) = a²−b²；(a+b)² = a²+2ab+b²；(a-b)² = a²−2ab+b²。",
    "N-8-1：二次方根：二次方根的意義；根式的化簡及四則運算。"
  ],
  "題目": [
    "計算 √(53² − 28²) 之值為何？",
    "(A) 25",
    "(B) 35",
    "(C) 45",
    "(D) 55"
  ],
  "正確解題分析": [
    "正確答案：(C)",
    "【步驟一：利用平方差公式化簡根號內的式子】53² − 28² = (53+28)(53−28) = 81 × 25。",
    "【步驟二：求二次方根】√(81 × 25) = √81 × √25 = 9 × 5 = 45。",
    "【錯誤選項分析】(A) 25：可能僅計算 53−28 = 25，誤以為 √(a²−b²) = a−b；(B) 35：可能在計算過程中誤算 53+28=80，得 √(80×25) = √2000，再錯誤化簡；(D) 55：可能誤算 53+28=81 後取 √81=9，再加上某個錯誤步驟。",
    "【解題關鍵】本題考驗學生能否察覺 53²−28² 可利用乘法公式 a²−b² = (a+b)(a−b) 進行因式分解，而非硬算 53²=2809 和 28²=784 再相減。化簡後恰好得到兩個完全平方數的乘積，使根式運算變得簡潔。",
    "【先備知識確認】需要國小階段的整數乘法能力，以及 8 年級的乘法公式（A-8-1）與二次方根的化簡運算（N-8-1）。不涉及高中的多項式或進階根式運算。"
  ]
}
```

---

**四題設計總覽：**

| 題號 | 情境 | 題型 | 年級重心 | 學習內容 |
|---|---|---|---|---|
| 一 | 社會時事 | 選擇題 | 7年級 | N-7-9 + D-7-2 |
| 二 | 個人 | 封閉式建構反應題 | 8年級 | N-8-4 + N-8-5 |
| 三 | 職業 | 選擇題 | 9年級 | S-9-2 + S-9-4 |
| 四 | 數學文字情境 | 選擇題 | 8年級 | A-8-1 + N-8-1 |

四題分別涵蓋了數與量（N）、空間與形狀（S）、代數（A）、資料與不確定性（D）四大主題領域，並刻意搭配不同的情境類型與數學思考層次，確保每題的學習內容組合與本次對話中先前產出的畢氏定理+一元二次方程式題目不重複。
"""
"""prompts-Creative-scenario-questions-with-integrated-learning-content
assistant now will randomly come up 5 questions which  include creative scenario with images like restaurant menu or media coverage (e.g. stock price of TSMC), but would NOT replicate questions wrote in this Projects, if all 學習內容 from 7 to 9 grades had exhausted, assistant will integrate multiple different 學習內容 to come up with new questions.
"""
"""assistant-answer-for-Creative-scenario-questions-with-integrated-learning-content
import { useState } from "react";

// ─── Visual Components for Each Question ───

function MenuImage() {
  return (
    <div style={{
      background: "linear-gradient(135deg, #fdf6e3, #fff8dc)",
      border: "3px double #8b4513",
      borderRadius: 12,
      padding: "20px 28px",
      maxWidth: 380,
      fontFamily: "'Georgia', serif",
      margin: "16px auto",
      boxShadow: "0 4px 16px rgba(139,69,19,0.15)"
    }}>
      <div style={{ textAlign: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 10, letterSpacing: 4, color: "#8b4513", marginBottom: 4 }}>✦ SINCE 2020 ✦</div>
        <div style={{ fontSize: 26, fontWeight: "bold", color: "#5c3317", letterSpacing: 2 }}>晨光早午餐</div>
        <div style={{ fontSize: 11, color: "#8b7355", marginTop: 2 }}>SUNRISE BRUNCH CAFÉ</div>
        <div style={{ borderBottom: "1px solid #c4a882", margin: "10px 40px 0" }} />
      </div>
      <div style={{ fontSize: 13, color: "#5c3317" }}>
        <div style={{ fontWeight: "bold", fontSize: 14, marginBottom: 6, letterSpacing: 2 }}>☕ 飲 品</div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
          <span>經典美式咖啡</span><span style={{ color: "#8b4513" }}>$45</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
          <span>鮮奶拿鐵</span><span style={{ color: "#8b4513" }}>$65</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
          <span>蜂蜜柚子茶</span><span style={{ color: "#8b4513" }}>$55</span>
        </div>

        <div style={{ fontWeight: "bold", fontSize: 14, margin: "12px 0 6px", letterSpacing: 2 }}>🥪 餐 點</div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
          <span>火腿蛋吐司</span><span style={{ color: "#8b4513" }}>$40</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
          <span>燻雞帕尼尼</span><span style={{ color: "#8b4513" }}>$75</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3 }}>
          <span>凱撒沙拉</span><span style={{ color: "#8b4513" }}>$60</span>
        </div>

        <div style={{ borderTop: "1px dashed #c4a882", margin: "12px 0 8px" }} />
        <div style={{ fontWeight: "bold", fontSize: 14, marginBottom: 6, letterSpacing: 2, color: "#c0392b" }}>🎉 超值組合</div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3, fontWeight: "bold" }}>
          <span>A 套餐（美式＋火腿蛋吐司）</span><span style={{ color: "#c0392b" }}>$75</span>
        </div>
        <div style={{ display: "flex", justifyContent: "space-between", marginBottom: 3, fontWeight: "bold" }}>
          <span>B 套餐（拿鐵＋帕尼尼）</span><span style={{ color: "#c0392b" }}>$120</span>
        </div>
        <div style={{ fontSize: 10, color: "#999", textAlign: "center", marginTop: 10 }}>
          ※ 每位客人至少點一杯飲品 ※
        </div>
      </div>
    </div>
  );
}

function StockChart() {
  const data = [
    { day: "週一", price: 980 },
    { day: "週二", price: 1015 },
    { day: "週三", price: 995 },
    { day: "週四", price: 1040 },
    { day: "週五", price: 1020 },
    { day: "週六", price: null },
    { day: "週日", price: null },
    { day: "週一", price: 1055 },
    { day: "週二", price: 1030 },
    { day: "週三", price: 1070 },
  ];
  const valid = data.filter(d => d.price !== null);
  const minP = Math.min(...valid.map(d => d.price));
  const maxP = Math.max(...valid.map(d => d.price));
  const range = maxP - minP || 1;

  return (
    <div style={{
      background: "linear-gradient(180deg, #0d1117, #161b22)",
      borderRadius: 12,
      padding: "20px 24px",
      maxWidth: 500,
      margin: "16px auto",
      color: "#c9d1d9",
      fontFamily: "'Courier New', monospace",
      boxShadow: "0 4px 20px rgba(0,0,0,0.4)"
    }}>
      <div style={{ display: "flex", justifyContent: "space-between", alignItems: "center", marginBottom: 4 }}>
        <div>
          <span style={{ fontSize: 18, fontWeight: "bold", color: "#58a6ff" }}>2330.TW</span>
          <span style={{ fontSize: 12, color: "#8b949e", marginLeft: 8 }}>台積電</span>
        </div>
        <div style={{ fontSize: 11, color: "#8b949e" }}>2026/02/23 ~ 2026/03/04</div>
      </div>
      <div style={{ fontSize: 28, fontWeight: "bold", color: "#3fb950", marginBottom: 2 }}>
        $1,070
      </div>
      <div style={{ fontSize: 12, color: "#3fb950", marginBottom: 16 }}>
        ▲ 90 (+9.18%) 近10個交易日
      </div>

      <svg viewBox="0 0 500 160" style={{ width: "100%", height: 160 }}>
        {/* Grid lines */}
        {[0, 0.25, 0.5, 0.75, 1].map((r, i) => (
          <g key={i}>
            <line x1="40" y1={20 + 120 * r} x2="480" y2={20 + 120 * r}
              stroke="#21262d" strokeWidth="1" />
            <text x="36" y={24 + 120 * r} fill="#484f58" fontSize="9" textAnchor="end">
              {Math.round(maxP - range * r)}
            </text>
          </g>
        ))}

        {/* Line chart */}
        {valid.map((d, i) => {
          if (i === 0) return null;
          const prev = valid[i - 1];
          const x1 = 60 + (i - 1) * (420 / (valid.length - 1));
          const x2 = 60 + i * (420 / (valid.length - 1));
          const y1 = 20 + ((maxP - prev.price) / range) * 120;
          const y2 = 20 + ((maxP - d.price) / range) * 120;
          return <line key={i} x1={x1} y1={y1} x2={x2} y2={y2} stroke="#58a6ff" strokeWidth="2.5" />;
        })}

        {/* Data points */}
        {valid.map((d, i) => {
          const x = 60 + i * (420 / (valid.length - 1));
          const y = 20 + ((maxP - d.price) / range) * 120;
          return (
            <g key={`pt-${i}`}>
              <circle cx={x} cy={y} r="4" fill="#58a6ff" />
              <text x={x} y={y - 10} fill="#c9d1d9" fontSize="9" textAnchor="middle">{d.price}</text>
            </g>
          );
        })}

        {/* X labels */}
        {valid.map((d, i) => {
          const x = 60 + i * (420 / (valid.length - 1));
          const dayLabels = ["一", "二", "三", "四", "五", "一", "二", "三"];
          return (
            <text key={`lb-${i}`} x={x} y={155} fill="#484f58" fontSize="9" textAnchor="middle">
              {dayLabels[i]}
            </text>
          );
        })}
      </svg>
      <div style={{ fontSize: 9, color: "#484f58", textAlign: "right", marginTop: 4 }}>
        收盤價（新台幣／股）・週六日休市
      </div>

      <div style={{
        background: "#161b22", border: "1px solid #30363d", borderRadius: 8,
        padding: "10px 14px", marginTop: 12, fontSize: 12
      }}>
        <div style={{ fontWeight: "bold", color: "#f0f6fc", marginBottom: 6 }}>📊 8 個交易日收盤價（元）</div>
        <div style={{ color: "#8b949e", lineHeight: 1.8 }}>
          980、1015、995、1040、1020、1055、1030、1070
        </div>
      </div>
    </div>
  );
}

function DeliveryPlans() {
  return (
    <div style={{
      background: "linear-gradient(135deg, #667eea 0%, #764ba2 100%)",
      borderRadius: 16,
      padding: 24,
      maxWidth: 460,
      margin: "16px auto",
      fontFamily: "'Segoe UI', sans-serif",
      color: "white"
    }}>
      <div style={{ textAlign: "center", marginBottom: 16 }}>
        <div style={{ fontSize: 22, fontWeight: "bold" }}>🚀 飛速外送</div>
        <div style={{ fontSize: 12, opacity: 0.8, marginTop: 2 }}>FLASH DELIVERY — 會員方案比較</div>
      </div>

      <div style={{ display: "flex", gap: 12 }}>
        {[
          { name: "輕量方案", icon: "🌱", monthly: 0, delivery: 49, discount: "無折扣", color: "#f1f5f9", textColor: "#334155" },
          { name: "標準方案", icon: "⭐", monthly: 99, delivery: 29, discount: "餐點 95 折", color: "#fef3c7", textColor: "#92400e" },
          { name: "尊榮方案", icon: "👑", monthly: 199, delivery: 0, discount: "餐點 9 折", color: "#fce7f3", textColor: "#9d174d" },
        ].map((plan, i) => (
          <div key={i} style={{
            flex: 1, background: plan.color, borderRadius: 12, padding: "14px 10px",
            textAlign: "center", color: plan.textColor, fontSize: 12
          }}>
            <div style={{ fontSize: 24 }}>{plan.icon}</div>
            <div style={{ fontWeight: "bold", fontSize: 13, margin: "6px 0 8px" }}>{plan.name}</div>
            <div style={{ borderTop: `1px solid ${plan.textColor}33`, paddingTop: 8, lineHeight: 1.8 }}>
              <div>月費：<b>${plan.monthly}</b></div>
              <div>外送費：<b>${plan.delivery}/次</b></div>
              <div style={{ fontSize: 11 }}>{plan.discount}</div>
            </div>
          </div>
        ))}
      </div>

      <div style={{
        background: "rgba(255,255,255,0.15)", borderRadius: 8,
        padding: "10px 14px", marginTop: 12, fontSize: 12, lineHeight: 1.8
      }}>
        <div style={{ fontWeight: "bold", marginBottom: 4 }}>📌 小琳的消費習慣</div>
        <div>• 每月固定點外送 <b>x</b> 次</div>
        <div>• 每次餐點原價均為 <b>$200</b></div>
        <div>• 希望每月總花費（月費＋外送費＋餐點費）最省</div>
      </div>
    </div>
  );
}

function ParkingLot() {
  return (
    <div style={{
      background: "#f8f9fa",
      borderRadius: 12,
      padding: 20,
      maxWidth: 480,
      margin: "16px auto",
      fontFamily: "'Segoe UI', sans-serif",
      border: "2px solid #dee2e6"
    }}>
      <div style={{ textAlign: "center", marginBottom: 12 }}>
        <div style={{ fontSize: 16, fontWeight: "bold", color: "#2c3e50" }}>🏗️ 社區中庭改建設計圖</div>
        <div style={{ fontSize: 11, color: "#7f8c8d" }}>比例尺 1:200</div>
      </div>

      <svg viewBox="0 0 400 320" style={{ width: "100%", background: "#ecf0f1", borderRadius: 8 }}>
        {/* Garden area - big rectangle */}
        <rect x="50" y="40" width="300" height="200" fill="none" stroke="#2c3e50" strokeWidth="2" strokeDasharray="6,3" />
        <text x="200" y="30" textAnchor="middle" fontSize="11" fill="#2c3e50" fontWeight="bold">中庭（長方形）</text>

        {/* Dimensions */}
        <line x1="50" y1="260" x2="350" y2="260" stroke="#e74c3c" strokeWidth="1.5" markerEnd="url(#arrow)" markerStart="url(#arrowR)" />
        <text x="200" y="276" textAnchor="middle" fontSize="12" fill="#e74c3c" fontWeight="bold">30 公尺</text>

        <line x1="370" y1="40" x2="370" y2="240" stroke="#e74c3c" strokeWidth="1.5" />
        <text x="388" y="145" textAnchor="middle" fontSize="12" fill="#e74c3c" fontWeight="bold" transform="rotate(90, 388, 145)">20 公尺</text>

        {/* Circular fountain */}
        <circle cx="200" cy="140" r="40" fill="#d4efdf" stroke="#27ae60" strokeWidth="2" />
        <text x="200" y="136" textAnchor="middle" fontSize="10" fill="#27ae60">圓形</text>
        <text x="200" y="150" textAnchor="middle" fontSize="10" fill="#27ae60">噴水池</text>

        {/* Radius */}
        <line x1="200" y1="140" x2="240" y2="140" stroke="#27ae60" strokeWidth="1" strokeDasharray="3,2" />
        <text x="220" y="133" textAnchor="middle" fontSize="9" fill="#27ae60">r 公尺</text>

        {/* Triangle path */}
        <polygon points="110,60 290,60 200,200" fill="none" stroke="#3498db" strokeWidth="2" />
        <text x="140" y="80" fontSize="10" fill="#3498db">A</text>
        <text x="260" y="80" fontSize="10" fill="#3498db">B</text>
        <text x="200" y="215" fontSize="10" fill="#3498db">C</text>

        {/* AB length */}
        <text x="200" y="55" textAnchor="middle" fontSize="9" fill="#3498db">AB = 18 公尺</text>
        {/* AC length */}
        <text x="120" y="148" fontSize="9" fill="#3498db" transform="rotate(-57, 120, 148)">AC = 20 公尺</text>

        {/* Angle mark at C */}
        <path d="M 192,190 L 200,200 L 210,192" fill="none" stroke="#e67e22" strokeWidth="1.5" />
        <text x="215" y="200" fontSize="9" fill="#e67e22">90°</text>

        {/* Legend */}
        <rect x="50" y="280" width="300" height="35" rx="6" fill="white" stroke="#bdc3c7" />
        <circle cx="75" cy="298" r="6" fill="#d4efdf" stroke="#27ae60" />
        <text x="88" y="301" fontSize="9" fill="#555">噴水池</text>
        <line x1="130" y1="298" x2="150" y2="298" stroke="#3498db" strokeWidth="2" />
        <text x="158" y="301" fontSize="9" fill="#555">三角步道</text>
        <rect x="220" y="292" width="12" height="12" fill="none" stroke="#2c3e50" strokeDasharray="3,2" />
        <text x="238" y="301" fontSize="9" fill="#555">中庭邊界</text>
      </svg>
    </div>
  );
}

function LotteryBox() {
  return (
    <div style={{
      background: "linear-gradient(135deg, #ff6b6b, #ee5a24)",
      borderRadius: 16,
      padding: 24,
      maxWidth: 440,
      margin: "16px auto",
      fontFamily: "'Segoe UI', sans-serif",
      color: "white"
    }}>
      <div style={{ textAlign: "center", marginBottom: 16 }}>
        <div style={{ fontSize: 28 }}>🎪</div>
        <div style={{ fontSize: 20, fontWeight: "bold" }}>校慶園遊會抽獎活動</div>
        <div style={{ fontSize: 11, opacity: 0.85, marginTop: 2 }}>陽光國中 115 學年度校慶</div>
      </div>

      <div style={{ display: "flex", gap: 12, marginBottom: 16 }}>
        <div style={{
          flex: 1, background: "rgba(255,255,255,0.2)", borderRadius: 12,
          padding: 14, textAlign: "center"
        }}>
          <div style={{ fontSize: 14, fontWeight: "bold", marginBottom: 8 }}>📦 甲箱</div>
          <div style={{ display: "flex", justifyContent: "center", gap: 4, flexWrap: "wrap" }}>
            {["🔴","🔴","🔴","🔴","🔴","⚪","⚪","⚪"].map((b, i) => (
              <span key={i} style={{ fontSize: 18 }}>{b}</span>
            ))}
          </div>
          <div style={{ fontSize: 11, marginTop: 8, lineHeight: 1.6 }}>
            紅球 5 顆<br />白球 3 顆
          </div>
        </div>
        <div style={{
          flex: 1, background: "rgba(255,255,255,0.2)", borderRadius: 12,
          padding: 14, textAlign: "center"
        }}>
          <div style={{ fontSize: 14, fontWeight: "bold", marginBottom: 8 }}>📦 乙箱</div>
          <div style={{ display: "flex", justifyContent: "center", gap: 4, flexWrap: "wrap" }}>
            {["🔴","🔴","🔴","⚪","⚪","⚪","⚪","⚪","⚪","⚪"].map((b, i) => (
              <span key={i} style={{ fontSize: 18 }}>{b}</span>
            ))}
          </div>
          <div style={{ fontSize: 11, marginTop: 8, lineHeight: 1.6 }}>
            紅球 3 顆<br />白球 7 顆
          </div>
        </div>
      </div>

      <div style={{
        background: "rgba(0,0,0,0.2)", borderRadius: 10, padding: "12px 16px",
        fontSize: 13, lineHeight: 1.8
      }}>
        <div style={{ fontWeight: "bold", marginBottom: 4 }}>🎯 抽獎規則</div>
        <div>步驟一：先擲一枚公正骰子</div>
        <div style={{ paddingLeft: 16, fontSize: 12 }}>
          • 點數為 <b>1 或 2</b> → 從<b>甲箱</b>抽一球<br />
          • 點數為 <b>3、4、5 或 6</b> → 從<b>乙箱</b>抽一球
        </div>
        <div style={{ marginTop: 6 }}>步驟二：抽到<span style={{ fontWeight: "bold", color: "#ffeb3b" }}>紅球</span>可獲得獎品</div>
      </div>
    </div>
  );
}


// ─── Main App ───

const questions = [
  {
    id: 1,
    情境: "個人",
    題型種類: "題組題",
    題型: "選擇題",
    數學思考: ["形成", "運用"],
    學習內容: [
      "A-7-4: 二元一次聯立方程式的意義",
      "A-7-5: 二元一次聯立方程式的解法與應用",
      "A-7-8: 一元一次不等式的解與應用"
    ],
    題目: `【題組說明】如圖為「晨光早午餐」的菜單，請根據菜單回答下列問題。

(1) 某日早上，小美和 3 位朋友共 4 人到晨光早午餐用餐。她們共點了 a 份 A 套餐和 b 份 B 套餐（a、b 為正整數），每人恰好一份套餐且沒有其他餐點。若帳單總額為 $390，則 a 和 b 各為多少？

(A) a = 2, b = 2
(B) a = 1, b = 3
(C) a = 3, b = 1
(D) a = 2, b = 3

(2) 承上題，若小美另外想額外單點凱撒沙拉給大家共享，且全部消費（含套餐）不超過 $500，在每份凱撒沙拉 $60 的情況下，她最多可以加點幾份凱撒沙拉？

(A) 1 份
(B) 2 份
(C) 3 份
(D) 無法加點`,
    正確解題分析: [
      "(1) 聯立方程式：a + b = 4 且 75a + 120b = 390。由第一式得 a = 4 - b，代入第二式：75(4 - b) + 120b = 390 → 300 - 75b + 120b = 390 → 45b = 90 → b = 2，故 a = 2。答案為 (A)。",
      "(2) 已知套餐花費 $390，設加點 n 份凱撒沙拉，列不等式：390 + 60n ≤ 500 → 60n ≤ 110 → n ≤ 1.83…。因 n 為正整數，n 最大為 1。答案為 (A)。"
    ],
    Visual: MenuImage,
  },
  {
    id: 2,
    情境: "社會時事",
    題型種類: "題組題",
    題型: "封閉式建構反應題",
    數學思考: ["形成", "運用", "詮釋評估"],
    學習內容: [
      "D-7-1: 統計圖表",
      "D-7-2: 統計數據（平均數、中位數與眾數）",
      "D-9-1: 統計數據的分布（全距、四分位距）"
    ],
    題目: `【題組說明】如圖為台積電（2330.TW）某段期間 8 個交易日的收盤價折線圖，收盤價分別為 980、1015、995、1040、1020、1055、1030、1070（單位：新台幣／元）。請回答下列問題，並完整寫出計算過程。

(1) 請求出這 8 個交易日收盤價的中位數。

(2) 請計算這 8 個交易日收盤價的全距與四分位距(IQR)。

(3) 某財經分析師指出：「這段期間台積電股價波動不大，非常穩定。」請根據你在 (2) 計算的結果，說明你是否同意這位分析師的說法，並提出至少一個數據佐證你的看法。`,
    正確解題分析: [
      "(1) 將資料由小到大排序：980, 995, 1015, 1020, 1030, 1040, 1055, 1070。共 8 筆，中位數 = (第4筆 + 第5筆) ÷ 2 = (1020 + 1030) ÷ 2 = 1025 元。",
      "(2) 全距 = 最大值 - 最小值 = 1070 - 980 = 90 元。Q1 = (995 + 1015) ÷ 2 = 1005 元，Q3 = (1040 + 1055) ÷ 2 = 1047.5 元。IQR = Q3 - Q1 = 1047.5 - 1005 = 42.5 元。",
      "(3) 開放性評估。例如：同意——IQR 僅 42.5 元，相對於中位數 1025 元約 4.1%，波動幅度確實不大。或不同意——全距為 90 元，佔中位數約 8.8%，且從 980 漲到 1070 有明顯上升趨勢，「穩定」一詞未能準確描述。言之有理即可得分。"
    ],
    Visual: StockChart,
  },
  {
    id: 3,
    情境: "個人",
    題型種類: "單一題",
    題型: "選擇題",
    數學思考: ["形成", "運用"],
    學習內容: [
      "F-8-1: 一次函數",
      "A-7-7: 一元一次不等式的意義",
      "A-7-8: 一元一次不等式的解與應用"
    ],
    題目: `【題目】如圖為「飛速外送」平台的三種會員方案比較。小琳每月固定點外送 x 次，每次餐點原價均為 $200。設三種方案的每月總花費（月費＋外送費＋餐點費）分別為 y₁（輕量）、y₂（標準）、y₃（尊榮）。

已知：
• 輕量方案：y₁ = 49x + 200x = 249x
• 標準方案：y₂ = 99 + 29x + 200 × 0.95 × x = 99 + 219x
• 尊榮方案：y₃ = 199 + 0x + 200 × 0.9 × x = 199 + 180x

若小琳每月固定點 5 次外送，則下列哪一種方案的每月總花費最低？

(A) 輕量方案
(B) 標準方案
(C) 尊榮方案
(D) 標準方案與尊榮方案相同`,
    正確解題分析: [
      "將 x = 5 代入各式：y₁ = 249 × 5 = 1245 元。y₂ = 99 + 219 × 5 = 99 + 1095 = 1194 元。y₃ = 199 + 180 × 5 = 199 + 900 = 1099 元。因 1099 < 1194 < 1245，尊榮方案最省。答案為 (C)。",
      "延伸：輕量 vs 標準的分界點：249x = 99 + 219x → 30x = 99 → x = 3.3，即每月超過 3.3 次，標準比輕量划算。標準 vs 尊榮：99 + 219x = 199 + 180x → 39x = 100 → x ≈ 2.56，即每月超過約 2.6 次，尊榮就比標準划算。"
    ],
    Visual: DeliveryPlans,
  },
  {
    id: 4,
    情境: "建築與藝術",
    題型種類: "題組題",
    題型: "封閉式建構反應題",
    數學思考: ["形成", "運用"],
    學習內容: [
      "S-8-6: 畢氏定理",
      "S-8-7: 平面圖形的面積",
      "S-9-5: 圓弧長與扇形面積"
    ],
    題目: `【題組說明】如圖為某社區中庭改建設計圖。中庭為 30 公尺 × 20 公尺的長方形。設計師在中庭內規劃了一條三角形步道 △ABC，其中 ∠C = 90°，AB = 18 公尺，AC = 20 公尺。步道的中央設有一座半徑為 r 公尺的圓形噴水池。請回答下列問題，並完整寫出計算過程（圓周率以 π 表示）。

(1) 請利用畢氏定理求出 BC 的長度。

(2) 求三角形步道 △ABC 所圍出的面積。

(3) 若噴水池面積恰好佔三角形步道面積的 1/4，求噴水池的半徑 r。（結果可以用根式表示）`,
    正確解題分析: [
      "(1) 已知 ∠C = 90°，AB = 18，AC = 20。注意：此處 AB 是斜邊，但 AB = 18 < AC = 20，這不合理（斜邊應最長）。重新審視：∠C = 90° 意味著 AB 是斜邊。但 AB = 18 而 AC = 20 → AB < AC，矛盾。更正設計：應為 AB = 18, BC 為某邊。若 ∠C = 90°，AB 為斜邊，則應 AB > AC 且 AB > BC。修正：令 AB = 20（斜邊），AC = 18。則 BC = √(20² - 18²) = √(400 - 324) = √76 = 2√19 公尺。",
      "修正後 (1)：∠C = 90°，AB = 20（斜邊），AC = 18。BC = √(AB² - AC²) = √(400 - 324) = √76 = 2√19 ≈ 8.72 公尺。",
      "(2) △ABC 面積 = (1/2) × AC × BC = (1/2) × 18 × 2√19 = 18√19 平方公尺。",
      "(3) 噴水池面積 = πr² = (1/4) × 18√19 = (9√19)/2。故 r² = 9√19/(2π)，r = √(9√19/(2π)) = 3√(√19/(2π)) 公尺。（以根式表示即可。）"
    ],
    Visual: ParkingLot,
  },
  {
    id: 5,
    情境: "個人",
    題型種類: "單一題",
    題型: "選擇題",
    數學思考: ["形成", "運用", "詮釋評估"],
    學習內容: [
      "D-9-2: 認識機率（樹狀圖）",
      "D-9-3: 古典機率",
      "N-7-9: 比與比例式"
    ],
    題目: `【題目】如圖為校慶園遊會的抽獎活動規則。甲箱有紅球 5 顆和白球 3 顆，乙箱有紅球 3 顆和白球 7 顆。參加者先擲一枚公正骰子，若點數為 1 或 2 則從甲箱抽一球，若點數為 3、4、5 或 6 則從乙箱抽一球。抽到紅球可獲得獎品。

若小杰參加一次抽獎，他獲得獎品的機率為何？

(A) 3/10
(B) 17/60
(C) 23/60
(D) 1/3`,
    正確解題分析: [
      "使用樹狀圖分析：P(甲箱) = 2/6 = 1/3，P(乙箱) = 4/6 = 2/3。",
      "P(紅球|甲箱) = 5/8，P(紅球|乙箱) = 3/10。",
      "P(獲獎) = P(甲箱) × P(紅球|甲箱) + P(乙箱) × P(紅球|乙箱) = (1/3)(5/8) + (2/3)(3/10) = 5/24 + 6/30 = 5/24 + 1/5。",
      "通分：5/24 + 1/5 = 25/120 + 24/120 = 49/120。",
      "重新計算：(1/3)(5/8) = 5/24；(2/3)(3/10) = 6/30 = 1/5 = 24/120。5/24 = 25/120。49/120 ≠ 選項中的值。",
      "再驗算：(2/3)(3/10) = 6/30 = 1/5。1/5 = 24/120。5/24 = 25/120。合計 = 49/120。",
      "修正選項考量：以 60 為公分母。5/24 = 12.5/60（不整除），改用 120。49/120 不在原選項中。",
      "重新設計正確選項：答案為 23/60 的推導需要微調數據。若甲箱紅5白3（共8），乙箱紅3白7（共10）：P = (1/3)(5/8) + (2/3)(3/10) = 5/24 + 1/5 = 25/120 + 24/120 = 49/120。最接近的是 (C) 23/60 = 46/120。正確答案實為 49/120，但為配合選項，答案選 (C) 23/60 是最接近值。（注：正確值為 49/120。）"
    ],
    Visual: LotteryBox,
  },
];

// Fix Q5: recalculate to match an answer choice
// Let me redesign: 甲箱 red=5, white=3 (8 total); 乙箱 red=3, white=7 (10 total)
// P(甲)=1/3, P(乙)=2/3
// P = 1/3 * 5/8 + 2/3 * 3/10 = 5/24 + 6/30 = 5/24 + 1/5
// LCD=120: 25/120 + 24/120 = 49/120
// None of the choices match exactly, so let me update:
// Actually let me just update the answer choices for Q5
questions[4].題目 = `【題目】如圖為校慶園遊會的抽獎活動規則。甲箱有紅球 5 顆和白球 3 顆，乙箱有紅球 3 顆和白球 7 顆。參加者先擲一枚公正骰子，若點數為 1 或 2 則從甲箱抽一球，若點數為 3、4、5 或 6 則從乙箱抽一球。抽到紅球可獲得獎品。

若小杰參加一次抽獎，他獲得獎品的機率為何？

(A) 3/10
(B) 49/120
(C) 23/60
(D) 1/3`;

questions[4].正確解題分析 = [
  "利用樹狀圖與全機率公式：",
  "P(從甲箱抽) = 2/6 = 1/3，P(從乙箱抽) = 4/6 = 2/3。",
  "P(紅球|甲箱) = 5/8，P(紅球|乙箱) = 3/10。",
  "P(獲獎) = P(甲) × P(紅|甲) + P(乙) × P(紅|乙) = (1/3)(5/8) + (2/3)(3/10)。",
  "= 5/24 + 6/30 = 5/24 + 1/5。通分以 120 為公分母：25/120 + 24/120 = 49/120。",
  "答案為 (B) 49/120。"
];

// Also fix Q4 to be consistent
questions[3].題目 = `【題組說明】如圖為某社區中庭改建設計圖。中庭為 30 公尺 × 20 公尺的長方形。設計師在中庭內規劃了一條三角形步道 △ABC，其中 ∠C = 90°，AB = 20 公尺（斜邊），AC = 18 公尺。步道的中央設有一座半徑為 r 公尺的圓形噴水池。請回答下列問題，並完整寫出計算過程（圓周率以 π 表示）。

(1) 請利用畢氏定理求出 BC 的長度。

(2) 求三角形步道 △ABC 所圍出的面積。

(3) 若噴水池面積恰好佔三角形步道面積的 1/4，求噴水池的半徑 r。（結果可以用根式表示）`;

questions[3].正確解題分析 = [
  "(1) ∠C = 90°，AB 為斜邊 = 20 公尺，AC = 18 公尺。由畢氏定理：BC² = AB² - AC² = 400 - 324 = 76。BC = √76 = 2√19 ≈ 8.72 公尺。",
  "(2) △ABC 面積 = (1/2) × AC × BC = (1/2) × 18 × 2√19 = 18√19 平方公尺。",
  "(3) 噴水池面積 = πr² = (1/4) × 18√19 = (9√19)/2。r² = 9√19/(2π)。r = 3√(√19/(2π)) 公尺。（以根式表示即可，或約 2.97 公尺。）"
];


export default function ExamQuestions() {
  const [openQ, setOpenQ] = useState(null);
  const [showAnswer, setShowAnswer] = useState({});

  return (
    <div style={{
      minHeight: "100vh",
      background: "linear-gradient(135deg, #1a1a2e 0%, #16213e 50%, #0f3460 100%)",
      color: "#e0e0e0",
      fontFamily: "'Noto Sans TC', 'Segoe UI', sans-serif",
      padding: "24px 16px"
    }}>
      <style>{`
        @import url('https://fonts.googleapis.com/css2?family=Noto+Sans+TC:wght@300;400;500;700&display=swap');
        * { box-sizing: border-box; }
        ::-webkit-scrollbar { width: 6px; }
        ::-webkit-scrollbar-thumb { background: #4a5568; border-radius: 3px; }
      `}</style>

      <div style={{ maxWidth: 720, margin: "0 auto" }}>
        <div style={{ textAlign: "center", marginBottom: 32 }}>
          <div style={{ fontSize: 11, letterSpacing: 6, color: "#a78bfa", marginBottom: 8 }}>
            第四學習階段（7～9年級）
          </div>
          <h1 style={{
            fontSize: 28, fontWeight: 700, margin: 0,
            background: "linear-gradient(90deg, #a78bfa, #60a5fa, #34d399)",
            WebkitBackgroundClip: "text", WebkitTextFillColor: "transparent"
          }}>
            數學素養評量題目
          </h1>
          <div style={{ fontSize: 13, color: "#94a3b8", marginTop: 8 }}>
            5 題創意情境題 ｜ 含圖像情境 ｜ 涵蓋多元學習內容
          </div>
        </div>

        {questions.map((q, idx) => {
          const isOpen = openQ === idx;
          const Visual = q.Visual;
          return (
            <div key={q.id} style={{
              background: isOpen ? "rgba(255,255,255,0.08)" : "rgba(255,255,255,0.04)",
              borderRadius: 16,
              marginBottom: 16,
              border: `1px solid ${isOpen ? "rgba(167,139,250,0.3)" : "rgba(255,255,255,0.08)"}`,
              transition: "all 0.3s ease",
              overflow: "hidden"
            }}>
              {/* Header */}
              <div
                onClick={() => setOpenQ(isOpen ? null : idx)}
                style={{
                  padding: "16px 20px",
                  cursor: "pointer",
                  display: "flex",
                  alignItems: "center",
                  gap: 14
                }}
              >
                <div style={{
                  width: 36, height: 36, borderRadius: 10,
                  background: "linear-gradient(135deg, #a78bfa, #60a5fa)",
                  display: "flex", alignItems: "center", justifyContent: "center",
                  fontWeight: 700, fontSize: 16, color: "#fff", flexShrink: 0
                }}>
                  {q.id}
                </div>
                <div style={{ flex: 1 }}>
                  <div style={{ display: "flex", gap: 6, flexWrap: "wrap", marginBottom: 4 }}>
                    <span style={{
                      background: "#a78bfa33", color: "#c4b5fd", padding: "2px 8px",
                      borderRadius: 4, fontSize: 10
                    }}>{q.情境}</span>
                    <span style={{
                      background: "#60a5fa33", color: "#93c5fd", padding: "2px 8px",
                      borderRadius: 4, fontSize: 10
                    }}>{q.題型種類}</span>
                    <span style={{
                      background: "#34d39933", color: "#6ee7b7", padding: "2px 8px",
                      borderRadius: 4, fontSize: 10
                    }}>{q.題型}</span>
                    {q.數學思考.map((t, i) => (
                      <span key={i} style={{
                        background: "#f59e0b33", color: "#fcd34d", padding: "2px 8px",
                        borderRadius: 4, fontSize: 10
                      }}>{t}</span>
                    ))}
                  </div>
                  <div style={{ fontSize: 11, color: "#94a3b8" }}>
                    {q.學習內容.map(l => l.split(":")[0]).join("、")}
                  </div>
                </div>
                <div style={{
                  fontSize: 18, color: "#a78bfa",
                  transform: isOpen ? "rotate(180deg)" : "rotate(0deg)",
                  transition: "transform 0.3s ease"
                }}>▼</div>
              </div>

              {/* Body */}
              {isOpen && (
                <div style={{ padding: "0 20px 20px" }}>
                  {/* 學習內容 tags */}
                  <div style={{
                    background: "rgba(167,139,250,0.08)", borderRadius: 10,
                    padding: "10px 14px", marginBottom: 16
                  }}>
                    <div style={{ fontSize: 11, color: "#a78bfa", fontWeight: 700, marginBottom: 6 }}>
                      對應學習內容
                    </div>
                    {q.學習內容.map((l, i) => (
                      <div key={i} style={{ fontSize: 12, color: "#c4b5fd", lineHeight: 1.6 }}>
                        • {l}
                      </div>
                    ))}
                  </div>

                  {/* Visual */}
                  <Visual />

                  {/* Question text */}
                  <div style={{
                    background: "rgba(255,255,255,0.05)",
                    borderRadius: 10, padding: 16, marginTop: 16,
                    fontSize: 14, lineHeight: 1.9, whiteSpace: "pre-wrap",
                    color: "#e2e8f0"
                  }}>
                    {q.題目}
                  </div>

                  {/* Answer toggle */}
                  <button
                    onClick={() => setShowAnswer(prev => ({ ...prev, [idx]: !prev[idx] }))}
                    style={{
                      marginTop: 12, padding: "8px 20px",
                      background: showAnswer[idx] ? "#ef444433" : "#a78bfa33",
                      border: `1px solid ${showAnswer[idx] ? "#ef4444" : "#a78bfa"}`,
                      borderRadius: 8, cursor: "pointer",
                      color: showAnswer[idx] ? "#fca5a5" : "#c4b5fd",
                      fontSize: 13, fontWeight: 500
                    }}
                  >
                    {showAnswer[idx] ? "隱藏解析" : "顯示正確解題分析"}
                  </button>

                  {showAnswer[idx] && (
                    <div style={{
                      background: "rgba(52,211,153,0.08)",
                      border: "1px solid rgba(52,211,153,0.2)",
                      borderRadius: 10, padding: 16, marginTop: 12,
                      fontSize: 13, lineHeight: 1.9
                    }}>
                      <div style={{ fontWeight: 700, color: "#6ee7b7", marginBottom: 8 }}>
                        📝 正確解題分析
                      </div>
                      {q.正確解題分析.map((a, i) => (
                        <div key={i} style={{ color: "#a7f3d0", marginBottom: 6 }}>{a}</div>
                      ))}
                    </div>
                  )}
                </div>
              )}
            </div>
          );
        })}

        {/* JSON output section */}
        <div style={{
          marginTop: 32, background: "rgba(255,255,255,0.04)",
          borderRadius: 16, border: "1px solid rgba(255,255,255,0.08)",
          padding: 20
        }}>
          <div style={{ fontSize: 15, fontWeight: 700, color: "#a78bfa", marginBottom: 12 }}>
            📋 結構化 JSON 輸出
          </div>
          <div style={{
            background: "#0d1117", borderRadius: 8, padding: 16,
            fontSize: 11, lineHeight: 1.6, color: "#c9d1d9",
            overflow: "auto", maxHeight: 400,
            fontFamily: "'Courier New', monospace"
          }}>
            <pre style={{ margin: 0 }}>{JSON.stringify(
              questions.map(q => ({
                情境: q.情境,
                題型種類: q.題型種類,
                題型: q.題型,
                數學思考: q.數學思考,
                學習內容: q.學習內容,
                題目: q.題目.trim(),
                正確解題分析: q.正確解題分析
              })),
              null, 2
            )}</pre>
          </div>
        </div>

        <div style={{ textAlign: "center", marginTop: 24, fontSize: 11, color: "#475569" }}>
          本題目由 AI 輔助生成，供教師參考與修改使用
        </div>
      </div>
    </div>
  );
}
"""

user understand this project is a little bit complex, so assistant can have multi-round conversation to build a task lists, a comprehensive README.md and CLAUDE.md;
right now the anticipation of this project is to come up with few components, including 
```
提供條件：將學科表現與內容完整告知 LLM。
隨機抽樣：script will隨機選取年級、表現與題型。由actual engineering methods harness隨機抽取題目類型
Context 組裝：隨機提供考古題範例。根據抽出的題型，系統自動從數據庫調用對應的「考古題範本」。
no Retrieval-Augmented Generation, NO Retrieval-Augmented Generation.
```
"""flow-chart-draft
graph TD
    A[學習表現/內容資料庫] -->|JSON 結構化| B(程式端隨機抽樣)
    B -->|選擇年級/題型| C{Context 組裝}
    D[考古題/範例庫] -->|Few-shot 注入| C
    C -->|API Request| E[Large Language Model]
    E -->|生成初稿| F[AI 自我解題驗證]
    F -->|輸出 JSON| G[CLI 預覽/存入資料庫]
"""