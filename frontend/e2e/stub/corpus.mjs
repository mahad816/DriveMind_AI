// Fictional research corpus: an MSc thesis on street trees and summer heat in the invented city of Larkhaven.
// Nothing here describes a real person, organisation or Drive.
const DOC = "application/vnd.google-apps.document", SHEET = "application/vnd.google-apps.spreadsheet",
  SLIDES = "application/vnd.google-apps.presentation", PDF = "application/pdf", TXT = "text/plain", MD = "text/markdown",
  DOCX = "application/vnd.openxmlformats-officedocument.wordprocessingml.document",
  XLSX = "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet", PNG = "image/png", CSV = "text/csv",
  ZIP = "application/zip";

const key = [
  ["Chapter 3 – Methods draft v4", DOC, "Thesis/Drafts", "indexed", "2026-11-23T16:20:00Z"],
  ["Supervisor feedback – 14 October", DOC, "Thesis/Feedback", "indexed", "2026-10-14T11:05:00Z"],
  ["Larkhaven canopy survey 2026 (cleaned)", SHEET, "Thesis/Data", "indexed", "2026-11-18T09:40:00Z"],
  ["Fieldwork budget 2026", SHEET, "Admin/Finance", "indexed", "2026-11-12T14:00:00Z"],
  ["Literature review – urban heat islands", DOC, "Thesis/Drafts", "indexed", "2026-11-02T10:15:00Z"],
  ["Ethics approval letter", PDF, "Admin", "indexed", "2026-07-30T08:00:00Z"],
  ["thermal_transects_notes.txt", TXT, "Thesis/Data/Transects", "indexed", "2026-09-21T18:30:00Z"],
  ["Committee presentation – progress review", SLIDES, "Thesis/Presentations", "indexed", "2026-10-28T13:00:00Z"],
  ["analysis-plan.md", MD, "Thesis", "indexed", "2026-11-20T21:10:00Z"],
  ["Interview transcripts – residents (anonymised)", DOCX, "Thesis/Data/Interviews", "indexed", "2026-10-05T15:45:00Z"],
  ["Final_budget_2026_FINAL_revised_v3 (copy) – do not edit, ask before changing anything in this sheet", XLSX, "Admin/Finance/Archive/2026/Old versions", "indexed", "2026-08-02T12:00:00Z"],
  ["Sensor calibration log", CSV, "Thesis/Data/Sensors", "indexed", "2026-09-10T07:20:00Z"],
  ["Chapter 1 – Introduction draft v2", DOC, "Thesis/Drafts", "discovered", "2026-11-21T19:00:00Z"],
  ["Chapter 2 – Study area", DOC, "Thesis/Drafts", "discovered", "2026-11-19T17:30:00Z"],
  ["Chapter 4 – Results (outline)", DOC, "Thesis/Drafts", "discovered", "2026-11-24T08:45:00Z"],
  ["Street tree inventory – council extract", XLSX, "Thesis/Data", "discovered", "2026-09-02T09:00:00Z"],
  ["Scanned field sheets – July", PDF, "Thesis/Data/Field sheets", "skipped", "2026-07-25T16:00:00Z"],
  ["Scanned consent forms batch 2", PDF, "Admin/Ethics", "skipped", "2026-07-26T10:00:00Z"],
  ["Drone survey export (corrupted)", PDF, "Thesis/Data/Drone", "failed", "2026-08-19T12:30:00Z"],
  ["Heat map draft – district 4", PNG, "Thesis/Figures", "failed", "2026-10-11T14:10:00Z"],
  ["Weather station archive 2015–2025", ZIP, "Thesis/Data/Weather", "discovered", "2026-06-30T09:00:00Z"],
  ["Reading list", DOC, "Thesis", "discovered", "2026-11-22T20:00:00Z"],
  ["Conference abstract – Urban Climate Forum (locked)", DOC, "Thesis/Outputs", "discovered", "2026-11-10T09:00:00Z"],
  ["Scanned receipts – equipment", PDF, "Admin/Finance/Receipts", "discovered", "2026-09-15T11:00:00Z"],
  ["Transect route map", PNG, "Thesis/Figures", "discovered", "2026-09-01T10:00:00Z"],
];
const folders = ["Thesis/Reading/Articles", "Thesis/Reading/Books", "Teaching/TA – Geography 210", "Admin/Forms", "Personal/Applications",
  "Thesis/Data/Raw", "Thesis/Figures/Drafts", "Department/Seminars", "Thesis/Meetings"];
const stems = ["Meeting notes", "Seminar notes", "Article summary", "Lab group minutes", "Tutorial plan", "Data dictionary", "Figure caption ideas",
  "Field day checklist", "Draft paragraph", "Reviewer response", "Grant application notes", "Weekly log"];
const types = [DOC, DOC, DOC, PDF, SHEET, TXT, DOCX, SLIDES, MD, CSV];
const generated = [];
for (let i = 0; i < 230; i++) {
  const stem = stems[i % stems.length], folder = folders[(i * 7) % folders.length];
  const month = 1 + (i % 11), day = 1 + ((i * 3) % 27);
  const date = `2026-${String(month).padStart(2, "0")}-${String(day).padStart(2, "0")}T${String(8 + (i % 10)).padStart(2, "0")}:00:00Z`;
  const ext = types[i % types.length] === TXT ? ".txt" : types[i % types.length] === MD ? ".md" : types[i % types.length] === CSV ? ".csv" : "";
  generated.push([`${stem} ${String(i + 1).padStart(3, "0")}${i % 17 === 0 ? " – long title kept exactly as it appears in Drive so the layout is tested" : ""}${ext}`,
    types[i % types.length], folder, i % 29 === 0 ? "indexed" : "discovered", date]);
}
const files = [...key, ...generated].map(([name, mime, folder, status, modified]) => ({ name, mime, folder, status, modified }));

// Passages (one per cited chunk). Snippets are exact substrings, so highlights can be matched honestly.
const chunks = [
  { chunk_id: "c0a10000-0000-4000-8000-000000000001", file: "Chapter 3 – Methods draft v4", index: 6,
    text: "3.4 Sampling. Streets were stratified by district and by dominant tree species before selection. The current draft states that forty street segments were sampled, but it does not yet justify why forty segments give enough statistical power, and the power calculation from the analysis plan has not been carried over. Segments with active construction were excluded during the July visits.",
    snippet: "it does not yet justify why forty segments give enough statistical power" },
  { chunk_id: "c0a10000-0000-4000-8000-000000000002", file: "Supervisor feedback – 14 October", index: 2,
    text: "General comments. The structure works. Two things before the committee sees it: first, add a short limitations paragraph to the results section that addresses sensor drift and the single summer of data; second, move the long description of the council inventory into an appendix. Minor: define 'canopy cover' once, early, and use the same definition throughout.",
    snippet: "add a short limitations paragraph to the results section that addresses sensor drift and the single summer of data" },
  { chunk_id: "c0a10000-0000-4000-8000-000000000003", file: "Larkhaven canopy survey 2026 (cleaned)", index: 0,
    text: "Summary tab. Across 40 segments, mean afternoon surface temperature fell by about 0.31 °C for every additional 10 percentage points of canopy cover (Pearson r = −0.72). District 4 (Harbour) and District 9 (Old Mill) sit well above the trend line: both have high canopy cover but surfaces that stay hot, likely because of dark roofing and wide paved car parks.",
    snippet: "mean afternoon surface temperature fell by about 0.31 °C for every additional 10 percentage points of canopy cover" },
  { chunk_id: "c0a10000-0000-4000-8000-000000000004", file: "Larkhaven canopy survey 2026 (cleaned)", index: 1,
    text: "Outliers tab. District 4 (Harbour) and District 9 (Old Mill) sit well above the trend line: both have high canopy cover but surfaces that stay hot. District 12 (Northfield) is below the line with low canopy and cool readings, which matches its proximity to the reservoir.",
    snippet: "District 12 (Northfield) is below the line with low canopy and cool readings" },
  { chunk_id: "c0a10000-0000-4000-8000-000000000005", file: "Fieldwork budget 2026", index: 0,
    text: "Totals. Allocated: 2,400. Spent to date: 1,630 (sensors 980, transport 410, printing 90, participant vouchers 150). Remaining: 770. The second round of thermal transects in February is estimated at 520, leaving a contingency of 250.",
    snippet: "Spent to date: 1,630 (sensors 980, transport 410, printing 90, participant vouchers 150). Remaining: 770." },
  { chunk_id: "c0a10000-0000-4000-8000-000000000006", file: "analysis-plan.md", index: 3,
    text: "## Power\nWith an expected correlation of r = 0.45, alpha 0.05 and power 0.8, a minimum of 36 segments is required. Forty segments were planned to allow for four exclusions.",
    snippet: "a minimum of 36 segments is required" },
  { chunk_id: "c0a10000-0000-4000-8000-000000000007", file: "thermal_transects_notes.txt", index: 4,
    text: "21 Sept, evening transect. Sensor B read 0.6 °C high against the reference at the start and 0.9 °C high at the end. Drift correction applied in the calibration log. Harbour car park still radiating heat at 21:30.",
    snippet: "Sensor B read 0.6 °C high against the reference at the start and 0.9 °C high at the end" },
];
const cite = (i, files) => {
  const c = chunks[i], file = files.find(f => f.name === c.file);
  return file ? { chunk_id: c.chunk_id, drive_file_id: file.id, filename: c.file, snippet: c.snippet, score: 0.82 - i * 0.03 } : null;
};
function answerFor(question, liveFiles) {
  const q = question.toLowerCase();
  const pick = (ids, answer) => {
    const citations = ids.map(i => cite(i, liveFiles)).filter(Boolean);
    // Renumber markers to the citations that exist (a file that is not present cannot be cited).
    return { answer: citations.length === ids.length ? answer : answer.replace(/\s?\[\d+\]/g, ""), citations: citations.length === ids.length ? citations : [] };
  };
  if (/recipe|weather tomorrow|football|capital of/.test(q))
    return { answer: "I couldn't find anything about that in your prepared documents. They cover the Larkhaven street-tree study, its data, budget and feedback.", citations: [] };
  if (/budget|money|spent|cost/.test(q))
    return pick([4], "About **770** of the 2,400 fieldwork allocation is left [1].\n\nSpending so far:\n\n- Sensors: 980\n- Transport: 410\n- Printing: 90\n- Participant vouchers: 150\n\nThe February transects are estimated at 520, which would leave a contingency of roughly 250 [1].");
  if (/outlier|district/.test(q))
    return pick([3, 2], "Three districts stand out from the trend [1]:\n\n| District | Canopy | Surface temperature | Likely reason |\n|---|---|---|---|\n| 4 · Harbour | High | Hot | Dark roofing, paved car parks |\n| 9 · Old Mill | High | Hot | Dark roofing |\n| 12 · Northfield | Low | Cool | Next to the reservoir |\n\nThe first two are above the regression line despite high canopy cover [2]; Northfield is below it [1].");
  if (/canopy|temperature|correlat|link/.test(q))
    return pick([2, 6], "The link is fairly strong. Mean afternoon surface temperature fell by about 0.31 °C for every 10 percentage points of extra canopy cover, with r = −0.72 across 40 segments [1].\n\nOne caution: sensor B drifted upward by up to 0.9 °C during the September transects, so the correction in the calibration log matters for the evening readings [2].");
  if (/feedback|supervisor|comment/.test(q))
    return pick([1], "The October feedback asks for two changes before the committee review [1]:\n\n1. Add a limitations paragraph to the results section covering sensor drift and the single summer of data.\n2. Move the council inventory description to an appendix.\n\nIt also asks you to define *canopy cover* once, early, and use that definition throughout [1].");
  if (/script|code|r code|python/.test(q))
    return pick([5], "The analysis plan sets the minimum sample at 36 segments [1]. A quick check in R:\n\n```r\nlibrary(pwr)\npwr.r.test(r = 0.45, sig.level = 0.05, power = 0.8)\n# n ≈ 36\n```\n\nForty were planned so that four exclusions are still safe [1].");
  if (/method|chapter 3|submission|need/.test(q))
    return pick([0, 5, 1], "The methods chapter has two clear gaps.\n\n**Sampling justification.** The draft says forty street segments were sampled but does not yet explain why that is enough [1]. The analysis plan already has the answer: a power calculation that needs at least 36 segments [2]. Carrying that paragraph over would close the gap.\n\n**Limitations.** Your supervisor asked for a limitations paragraph covering sensor drift and the single summer of data [3]. It belongs in the results chapter, but the methods chapter should point to it.\n\nEverything else in the October feedback is minor wording.");
  return pick([0, 2], "Your prepared documents describe a study of forty street segments in Larkhaven [1], which found that more canopy cover goes with cooler afternoon surfaces [2]. Ask about the methods, the survey results, the budget or the supervisor's feedback for more detail.");
}
const textFor = name => chunks.filter(c => c.file === name).map(c => c.text).join("\n\n") ||
  `${name}\n\nSynthetic text content for preview. This file belongs to the fictional Larkhaven study.`;
const prepOutcome = name => /scanned/i.test(name) ? "skip" : /corrupted/i.test(name) ? "document" : /\(locked\)/.test(name) ? "provider" : "ok";
export const corpus = { files, chunks, textFor, prepOutcome };
export { answerFor };
