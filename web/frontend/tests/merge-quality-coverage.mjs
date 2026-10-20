import {readFileSync, readdirSync, writeFileSync, mkdirSync} from 'node:fs';
import coverageLib from 'istanbul-lib-coverage';

const merged = coverageLib.createCoverageMap(JSON.parse(readFileSync('test-output/quality-coverage/coverage-final.json', 'utf8')));
for (const filename of readdirSync('test-output/browser-coverage').filter(name => name.endsWith('.json'))) {
  merged.merge(JSON.parse(readFileSync('test-output/browser-coverage/' + filename, 'utf8')));
}
mkdirSync('test-output/quality-coverage', {recursive: true});
writeFileSync('test-output/quality-coverage/combined.json', JSON.stringify(merged));
const summary = {total: merged.getCoverageSummary().toJSON()};
for (const file of merged.files()) summary[file] = merged.fileCoverageFor(file).toSummary().toJSON();
writeFileSync('test-output/quality-coverage/combined-summary.json', JSON.stringify(summary, null, 2));
console.log(JSON.stringify(summary.total, null, 2));
