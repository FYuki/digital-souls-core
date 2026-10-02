// Node's official reporter event stream supplies per-file and final summaries.
// Empty files get a synthetic pass but no per-file test summary in Node 24.19.0.
export default async function* requiredTests(source) {
  const files = [];
  let total;
  let incomplete = false;
  for await (const { type, data } of source) {
    if (type === 'test:summary') {
      if (data.file) files.push(data);
      else total = data;
    } else if (type === 'test:pass' || type === 'test:fail') {
      const status = data.skip ? 'SKIP' : data.todo ? 'TODO' : type === 'test:fail' ? 'FAIL' : 'PASS';
      incomplete ||= status !== 'PASS';
      yield `${status}: ${data.name}\n`;
      if (data.details.error) yield `${data.details.error.stack ?? data.details.error}\n`;
    } else if (type === 'test:stderr' || type === 'test:stdout') {
      yield data.message;
    }
  }
  const complete = summary => summary.success === true && summary.counts.tests > 0 &&
    ['failed', 'skipped', 'todo', 'cancelled'].every(key => summary.counts[key] === 0);
  const registered = files.reduce((sum, file) => sum + file.counts.tests, 0);
  if (incomplete || !total || !files.length || !complete(total) ||
      !files.every(complete) || total.counts.tests !== registered) {
    process.exitCode = 1;
    yield 'FAIL: required tests must be registered and pass; empty files, skip, todo, cancellation and failures are forbidden.\n';
  } else {
    yield `PASS: ${registered} registered required tests; no skips, todos or cancellations.\n`;
  }
}
