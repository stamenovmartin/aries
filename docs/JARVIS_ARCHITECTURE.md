# ARIES / Jarvis — target architecture

Green: implemented bounded capabilities. Amber: partial or current integration. Purple dashed: future work. This is the target system, not a claim that everything is complete.

```mermaid
flowchart TB
  U["ТИ · текст / команди / повратни информации"]
  subgraph SURFACE["01 · ARIES DESKTOP"]
    direction LR
    TOP["ARIES + мали икони горе<br/>без sidebar / долна лента"]
    CMD["Command palette<br/>што сакаш да направи"]
    WIN["Посебен прозорец по задача<br/>резиме · слика · извори · задржи отворено"]
    MON["Monitor<br/>ред · чекори · отворени прозорци · резултати"]
    LEARN["Learning<br/>корекции · трајни правила · историја"]
    VOICE["Глас / wake word / разговор"]
  end
  subgraph CONTROL["02 · КОНТРОЛА И ПЛАНИРАЊЕ"]
    direction LR
    API["Локален ARIES API<br/>авторизација · поставки · валидација"]
    QUEUE["Траен ред на задачи<br/>идентификатор · статус · откажување"]
    PLAN["Goal planner + локален модел<br/>цел → чекор → набљудување → следен чекор"]
    RES["Scheduler<br/>3 независни задачи · брави за заеднички ресурси"]
    GATE["Дозволи и точни цели<br/>проверка пред чувствителна промена"]
    LIFE["Животен циклус на прозорци<br/>создаден од која задача · затвори по крај · pin"]
  end
  subgraph TOOLS["03 · ИЗВРШУВАЊЕ"]
    WEB["Контролиран browser<br/>јавни страни · DOM · линкови · полиња"]
    DESK["Desktop / AT-SPI<br/>апликации · прозорци · достапни контроли"]
    FILE["Датотеки и инсталации<br/>пребарај · создај · премести · Trash · пакети"]
    CODE["Развојни задачи<br/>генерирај Python · sandbox · тест · поправка · VS Code"]
    NEWS["Вести и читање<br/>реални извори · извлечен текст · AI резиме · слика"]
    ACC["Најавени сервиси и конектори<br/>пошта · календар · GitHub · други сметки"]
    WIDE["Широка контрола на апликации<br/>посложени цели и сигурно закрепнување"]
  end
  subgraph EVIDENCE["04 · НАБЉУДУВАЊЕ И ПРОВЕРКА"]
    direction LR
    OBS["Свежа состојба<br/>отворено / затворено / фокус / недостапно"]
    CHECK["Независна проверка<br/>DOM · датотеки · излез · нов UI елемент"]
    STORE[("Локална трајна база<br/>задачи · докази · преференции · audit")]
    EVAL["Евалуација<br/>успех · неуспех · време · токени · поправки"]
  end
  subgraph IMPROVE["05 · УЧЕЊЕ И ЦЕЛНА ЕВОЛУЦИЈА"]
    PREF["Експлицитни правила<br/>достапни поставки + контекст за идни планови"]
    MEM["Долгорочен личен контекст<br/>проектна и разговорна меморија"]
    DATA["Оценети задачи<br/>цел · чекори · докази · твоја корекција"]
    COMP["Споредба на retrieval верзии<br/>фиксни случаи · регресии · избор · враќање"]
    TRAIN["Идна RL / подобрување на политика<br/>кандидат → offline eval → регресии"]
    RELEASE["Контролирано унапредување<br/>мерено подобрување · верзија · rollback"]
  end
  U --> SURFACE --> CONTROL --> TOOLS --> EVIDENCE --> IMPROVE
  TOP --> CMD --> WIN
  TOP --> MON --> LEARN
  VOICE -.-> CMD
  API --> QUEUE --> RES --> PLAN --> GATE --> LIFE
  WEB --- DESK --- FILE
  CODE --- NEWS
  ACC --- WIDE
  OBS --> CHECK --> STORE --> EVAL
  PREF --> MEM
  DATA --> COMP
  COMP -.-> TRAIN -.-> RELEASE
  classDef working fill:#102d31,stroke:#48d9ba,color:#e5fff8,stroke-width:2px
  classDef partial fill:#302918,stroke:#e8b95b,color:#fff4d8,stroke-width:2px
  classDef future fill:#252039,stroke:#b09ae8,color:#f1eaff,stroke-dasharray:5 4
  class U,API,QUEUE,RES,GATE,WEB,FILE,NEWS,CHECK,STORE,EVAL,CMD,WIN,MON,LEARN working
  class TOP,PLAN,LIFE,DESK,CODE,OBS,PREF,MEM partial
  class VOICE,ACC,WIDE,TRAIN,RELEASE future
  class DATA,COMP working
```

Feedback currently updates supported settings and supplies explicit preferences to the local goal planner. It does not train model weights. Desktop top-panel changes require a new GNOME session; native response windows can reload independently.
