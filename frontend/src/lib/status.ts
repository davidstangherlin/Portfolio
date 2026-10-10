// The nightly data's status in words (statusLines() in web/app.js): the
// dashboard's footer and the menu bar's data chip.
import { dateTime, longDate, plural, timeOnly } from "./format";

export interface Status {
  as_of: string | null; stale: boolean; expected: string | null;
  last_run: { status: string; started: string | null; finished: string; errors: number; file: string } | null;
}
export function statusLines(st: Status): string[] {
  const lines: string[] = [];
  lines.push(st.as_of ? `Prices and valuations as at ${longDate(st.as_of)}.` : "No valuations yet.");
  if (st.stale) lines.push(`Expected data for ${longDate(st.expected as string)}. Check the nightly job ran (or it was a public holiday).`);
  const run = st.last_run;
  if (!run) lines.push("No nightly run log found in the logs folder on this PC.");
  else if (run.status === "ok") lines.push(`Last nightly run ${dateTime(run.started as string)}, finished ${timeOnly(run.finished)} with no errors.`);
  else if (run.status === "errors") lines.push(`Last nightly run ${dateTime(run.started as string)}, finished ${timeOnly(run.finished)}. ${plural(run.errors, "company", "companies")} could not be updated (usually gaps in Yahoo's data). See logs\\${run.file}.`);
  else if (run.status === "crashed") lines.push(`Last nightly run ${dateTime(run.started as string)}: a step crashed, so some data may not have updated. See logs\\${run.file}.`);
  else if (run.status === "running") lines.push(`Nightly run in progress, started ${dateTime(run.started as string)}.`);
  else lines.push(`Last nightly run${run.started ? " " + dateTime(run.started) : ""} did not finish. See logs\\${run.file}. A log that simply stops was usually ended from outside: the task stopped when the PC stopped being idle, its window was closed, or the PC slept (README, Daily Automation, has the right Task Scheduler settings).`);
  return lines;
}
