# iHomeegy for Home Assistant

Control your iHomeegy units from Home Assistant, **locally**: no cloud, no internet needed.

Home Assistant joins your units the same way a family member does: the owner invites it from the iHomeegy app and
chooses which cards it may control. Every message is encrypted end to end (the same Noise protocol the iHomeegy app
uses), and the unit itself checks every command against the cards it was given.

## What you get

| Card in the app | In Home Assistant |
|---|---|
| ON/OFF lines, Energy Meter relay | Switch |
| Dimmers, DC LED dimmer, RGB strip | Light |
| Shutter | Cover (open / close / stop / position) |
| Fan | Fan (speeds) |
| Water / gas valve | Valve |
| Door lock | Lock |
| Gate pulse | Button |
| Thermostat | Climate |
| Siren | Siren |
| Inputs, RF hub sensors | Binary sensor (door, window, motion, smoke, gas, water leak, ...) |
| Temperature / humidity, Energy Meter readings | Sensor |
| Universal IR: TV remotes | Media player (power, volume, mute, channel up / down, channel number, inputs) |
| Universal IR: air conditioner remotes | Climate (off, modes, temperature, fan, swing) |

Universal IR remotes are made in the iHomeegy app; a remote added, changed or deleted there shows up in Home
Assistant within 5 minutes. A TV or an A/C never answers an infrared remote, so Home Assistant shows the last
setting sent (from Home Assistant, the app or a scene). Other remote kinds (fan, receiver, ...) are not shown yet.

Changes made in the iHomeegy app, by automations in the unit or by the wall switch show up in Home Assistant at once
(local push).

## Install (HACS)

1. HACS → ⋮ → **Custom repositories** → add `https://github.com/iHomeegy/ihomeegy-ha`, type **Integration**.
2. Find **iHomeegy** in HACS, **Download**, then restart Home Assistant.

## Add your units

1. In the iHomeegy app (owner or admin): **Members → Invite someone → With a QR code**, name it `Home Assistant`,
   choose the units and the cards it may control, then tap **Copy the code instead**.
2. In Home Assistant: **Settings → Devices & services → Add integration → iHomeegy**, paste the code.

The code works once and for 15 minutes. Home Assistant must be on the same network as the units.
Home Assistant shows up in the app's member list; removing it there takes its access away at once.

---

<div dir="rtl">

# iHomeegy لـ Home Assistant (بالعربية)

تحكَّم في وحدات iHomeegy من Home Assistant **محليًّا**: دون سحابة ودون حاجة إلى الإنترنت.

ينضم Home Assistant إلى وحداتك كما ينضم أي فرد من أفراد المنزل: يدعوه المالك من تطبيق iHomeegy ويختار الكروت
التي يُسمح له بالتحكم فيها. كل رسالة مشفَّرة من الطرف إلى الطرف (بنفس بروتوكول Noise الذي يستخدمه التطبيق)، والوحدة
نفسها تتحقق من كل أمر وفقًا للكروت الممنوحة له.

## ما الذي يظهر في Home Assistant

| الكارت في التطبيق | في Home Assistant |
|---|---|
| خطوط التشغيل والإيقاف، ومرحِّل عداد الطاقة | مفتاح (Switch) |
| الديمر، وديمر إضاءة LED المستمرة، وشريط RGB | إضاءة (Light) |
| الشيش (الستائر) | ستارة (Cover): فتح، إغلاق، إيقاف، نسبة الفتح |
| المروحة | مروحة (Fan) بسرعاتها |
| محبس المياه أو الغاز | محبس (Valve) |
| قفل الباب | قفل (Lock) |
| نبضة البوابة | زر (Button) |
| الثرموستات | تكييف (Climate) |
| السارينة | سارينة (Siren) |
| المداخل، وحساسات موزِّع RF | حساس ثنائي (Binary sensor): باب، نافذة، حركة، دخان، غاز، تسرب مياه، ... |
| الحرارة والرطوبة، وقراءات عداد الطاقة | حساس (Sensor) |
| الريموت الشامل (Universal IR): ريموتات الشاشات | مشغِّل وسائط (Media player): تشغيل وإيقاف، الصوت، كتم الصوت، القناة التالية والسابقة، رقم القناة، مصادر الدخل |
| الريموت الشامل (Universal IR): ريموتات التكييف | تكييف (Climate): إيقاف، الأوضاع، درجة الحرارة، سرعة المروحة، التأرجح |

تُنشأ ريموتات الريموت الشامل من تطبيق iHomeegy، وأي ريموت يُضاف أو يُعدَّل أو يُحذف هناك يظهر أثره في Home Assistant
خلال 5 دقائق. لا تَرُدّ الشاشة أو التكييف على ريموت الأشعة تحت الحمراء، لذلك يعرض Home Assistant آخر إعداد أُرسل (من
Home Assistant أو من التطبيق أو من مشهد). تبدأ الشاشة الجديدة بحالة «مطفأة» إلى أن تُشغَّل. أنواع الريموتات الأخرى
(المروحة، الريسيفر، ...) لا تظهر حاليًّا.

أي تغيير يحدث من تطبيق iHomeegy أو من الأتمتة داخل الوحدة أو من مفتاح الحائط يظهر في Home Assistant فورًا.

## التثبيت (عبر HACS)

1. افتح HACS، ثم اضغط على النقاط الثلاث ⋮ في الأعلى، ثم **Custom repositories** (المستودعات المخصصة).
2. في خانة Repository الصق الرابط `https://github.com/iHomeegy/ihomeegy-ha`، واختر النوع **Integration**، ثم اضغط **Add**.
3. ابحث في HACS عن **iHomeegy**، وافتحه، واضغط **Download** (تنزيل).
4. أعد تشغيل Home Assistant: **Settings** (الإعدادات) ← **System** (النظام) ← زر إعادة التشغيل في الأعلى ←
   **Restart Home Assistant**.

## إضافة وحداتك

1. في تطبيق iHomeegy (بحساب المالك أو مدير): ادخل إلى **أفراد المنزل** ← **ادعُ شخصًا** ← **برمز QR**.
2. اكتب الاسم `Home Assistant`، واختر الوحدات والكروت التي تريد أن يتحكم فيها، ثم اضغط **انسخ الكود بدل المسح**.
3. في Home Assistant: **Settings** (الإعدادات) ← **Devices & services** (الأجهزة والخدمات) ← **Add integration**
   (إضافة تكامل) ← ابحث عن **iHomeegy** واختره، ثم الصق الكود واضغط **Submit** (إرسال).

الكود يعمل مرة واحدة فقط ولمدة 15 دقيقة. يجب أن يكون Home Assistant على نفس الشبكة المحلية للوحدات.
يظهر Home Assistant في قائمة أفراد المنزل في التطبيق، وحذفه من هناك يُلغي صلاحيته فورًا.

</div>
