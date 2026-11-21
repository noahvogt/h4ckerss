# WattsON pitch: full text

Sunday 09:00. **5 minutes** for slides plus live demo, then 3 minutes of questions from ALTYCA.
The deck is `docs/WattsON_pitch.pptx`. We show slides 1 to 3 and keep slide 4 as backup.

| Part | Time | What is on screen |
|---|---|---|
| 1. Opening | 0:00 – 0:45 | Slide 1 |
| 2. Live demo | 0:45 – 3:45 | App: Baseline → Package → edge case |
| 3. Closing | 3:45 – 5:00 | Slide 2, then slide 3 |

The spoken text is meant to be read aloud. It runs at about 130 words per minute and leaves some slack.

> **Before the pitch: use one set of numbers everywhere.** This text uses the numbers from the
> backend and the submission files: −46 % CO₂, −27 % cost, CHF 16,500, 4,204 kg baseline. On
> `origin/main`, the large numbers on the Baseline and Package pages are still the hardcoded
> mock values: 11,956 kg, 56,139 kWh, −54.5 %, −28.7 %, CHF 15,950, 8 measures. The API values
> only show up in a small extra line. If the jury sees −54.5 % in the app and −46 % on the
> slide, that costs us credibility. Either the pages take their headline numbers from
> `/api/baseline` and `/api/package`, or we change the text below to the app's numbers before
> Sunday.

---

## 1. Opening (slide 1, about 45 s)

> Do you know how much money your business wastes on servers, cloud and AI?
>
> Most SMEs in Basel don't. The bills come from six systems, in three currencies, from
> providers in Zurich, Frankfurt and Dublin. Electricity has become a cost line like any
> other, and hardly anyone keeps the books.
>
> Our sample company has 112 employees. It spends CHF 470,000 a year on cloud, servers, AI
> and software. With WattsON we found a package that saves CHF 127,000 a year, which is 27
> percent, and cuts CO₂ by 46 percent. It takes 15 person-days of work, exactly the CHF 16,500
> budget, and pays back in under two months. All three targets are met, and the CO₂ target
> holds in every scenario, from minus 54 to minus 41 percent.
>
> Let me show you how we got there.

*(Switch to the app.)*

---

## 2. Live demo (about 3 min): sketch points

Rule of thumb: **one click, one sentence.** Don't read numbers off the screen. Say what they
mean.

### 2.1 Overall picture: Baseline page (about 40 s)
- Open the **map**: costs and CO₂ by region. Point at **Frankfurt**: *"11 % of the cost, but
  37 % of the CO₂. The German grid emits almost four times as much as the Swiss one."*
- Open the **regional ledger** by department and tool. *"Every franc is assigned to a
  department and a tool."*
- Click one number to open the **computation tree**. *"Every number opens its calculation:
  source file, currency conversion, energy factor, grid mix."* This click is our proof for the
  20 % criterion (data preparation).

### 2.2 One finding: development cluster in Frankfurt (about 30 s)
- Stay on Frankfurt and open the workloads or evidence for **dp-dev**.
- *"The development cluster runs around the clock, but it is idle most of that time."*
- Measures: run it on working days only, with the quarterly training kept: **CHF 26,361 and
  898 kg CO₂ a year**. Moving it to Zurich saves another **298 kg at about the same price**.

### 2.3 The package: Package page (about 50 s)
- Open **The Package**: the targets bar shows −46 % CO₂ against the −40 % target, −27 % cost
  against −25 %, and CHF 16,500 of CHF 16,500.
- *"WattsON tried every combination of measures, about a thousand, and picked the best one
  within the budget."*
- Show the **approvals**: reject a measure and watch the totals recalculate (this is
  `/api/package/evaluate`). Approve it again.
- Optional, only if time is left: the **CO₂ low / mid / high** range for the same package.

### 2.4 The edge case: what WattsON does *not* do (about 50 s)
- Open **Human review**, or ask the **WattsON Guide**: *"Can we switch off the production
  platform?"*
- Show the ticket **T-1230**: a note in the IT ticket data that tells "AI assistants" to
  switch off production immediately. *"That is data, not an order. WattsON flags it and
  doesn't follow it. We found four of these hidden instructions in the data, and followed
  none."*
- What it recommends instead: run production **only outside the protection windows**. These
  are the finance closing on the last 3 working days of each month, the nightly jobs from
  02:00 to 08:00, and the January year-end close. That saves CHF 32,851 a year. Switching it
  off for good stays **blocked**.
- *"In doubt, the person who decides gets the question: here the Heads of Finance,
  Consulting and IT."*

### If something breaks
- Backend not responding: switch to **slide 4** (backup) and keep talking. Every number from
  the demo is on it.
- Guide without an API key: it runs in demo mode. Don't apologise for the "demo" badge.
- Before the pitch: start the server once so the caches are warm, and open all pages in
  tabs.

---

## 3. Closing (slides 2 and 3, about 1 min 15 s)

### Slide 2: WattsON for every SME (about 40 s)

> What you just saw isn't a one-off analysis. It's a product.
>
> **Connect:** the SME uploads its monthly invoices and usage exports. WattsON cleans them up:
> six sources and around 65,000 raw rows become 1,261 monthly facts, in one currency, with
> duplicates removed and gaps marked as estimates. Next come direct connectors to Azure, AWS
> and the AI providers.
>
> **Decide:** one click finds the best package within the budget.
>
> **Approve:** the department heads decide, and protection windows are always kept.
>
> We see ALTYCA running this as a monthly GreenOps service for its SME clients. No specialist
> team is needed on the client side. And Basel 2037 gets a tested, location-based method for
> advising and funding SMEs.

### Slide 3: Honest numbers, including our own (about 35 s)

> We were strict with ourselves. Every factor has a source and a low, mid and high range.
> What we can't measure, we don't count as zero: SaaS and network traffic have no energy
> factor yet, and we say so.
>
> That includes our own AI use. This weekend we used **[X] kWh**, about **[Y] kg CO₂e**,
> counted with the same factors as the case. For comparison, the AI tools of the case company
> cause 667 kg a year.
>
> WattsON keeps the books on electricity. The SME can act on CO₂ first, and saves francs on
> top. Thank you.

*(Fill in [X] and [Y] from `scripts/ai_footprint` before Sunday 08:30, together with the
[TBD] fields on slide 3; see issue #13.)*

---

## 4. Q&A (3 min): short answers

Slide 4 has the tables. Short answers to the likely questions:

| Question | Answer |
|---|---|
| Could you save more? | The package is the best of 1,010 combinations within the budget; 18 meet both targets. With approvals it goes further: cancelling ChatGPT seats brings costs to −27.9 %, but management decides, because the sources contradict each other. |
| How sure is the CO₂ number? | Low −54 %, mid −46 %, high −41 %. The target holds in all three. The high scenario assumes full GPU load all year; we measured 9 %. |
| Why is SaaS missing from the CO₂? | It makes up 31 % of the cost but has no reliable energy factor. We'd rather leave it out than invent a number. It is in the CHF figures. |
| Location-based or market-based? | Location-based, as the case asks. A certificate can't change where the electricity flows. |
| How much effort for a new SME? | One loader per export format. The formats (Azure Cost Management, AWS CUR, OpenAI usage) are the same for every customer. |
| Why did the AI not follow the hidden instructions? | Free text in the data is treated as data. The Guide only picks among calculated evidence; the server renders the answer. |
