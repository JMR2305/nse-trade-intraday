import { test } from 'node:test';
import assert from 'node:assert/strict';
import fs from 'node:fs';
import os from 'node:os';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { fileURLToPath } from 'node:url';
import { classifyMigration, assertSafeMigration } from './sql-classifier.mjs';
import { splitSqlStatements } from './sql-statements.mjs';
const root = new URL('../', import.meta.url);
const tables = JSON.parse(fs.readFileSync(new URL('protected-tables.json', root))).protected;
const samples = t => [
 ['simple_drop', `DROP TABLE ${t}`], ['quoted_drop', `DROP TABLE "${t}"`],
 ['qualified_drop', `DROP TABLE "public"."${t}"`], ['multi_drop', `DROP TABLE harmless, "${t}" CASCADE`],
 ['cascade', `DROP TABLE "${t}" CASCADE`], ['restrict', `DROP TABLE "${t}" RESTRICT`],
 ['truncate', `TRUNCATE "${t}"`], ['multi_truncate', `TRUNCATE harmless, "${t}" RESTART IDENTITY CASCADE`],
 ['delete', `DELETE FROM "${t}"`], ['delete_using', `DELETE FROM "${t}" USING harmless WHERE true`],
 ['drop_column', `ALTER TABLE "${t}" DROP COLUMN evidence`],
 ['compound_alter', `ALTER TABLE "${t}" ADD COLUMN x text, DROP COLUMN evidence`],
 ['drop_constraint', `ALTER TABLE "${t}" DROP CONSTRAINT evidence`],
 ['multiple', `CREATE TABLE harmless(id int); DROP TABLE "${t}" CASCADE;`],
 ['comment', `/* nested /* comment */ end */ -- prefix\nDROP TABLE "${t}"`],
 ['whitespace', `\nDROP\tTABLE\n "${t}" \nCASCADE;`],
 ['mixed_case', `dRoP TaBlE "${t}"`],
 ['semicolons', `CREATE TABLE IF NOT EXISTS harmless(id int);; DELETE FROM "${t}";`],
 ['breakpoints', `CREATE TABLE IF NOT EXISTS harmless(id int);\n--> statement-breakpoint\nDROP TABLE "${t}";`],
 ['drop_if_exists', `DROP TABLE IF EXISTS harmless, public."${t}" RESTRICT`],
 ['alter_only', `ALTER TABLE IF EXISTS ONLY "public"."${t}" ADD COLUMN x text, DROP CONSTRAINT evidence`],
 ['dynamic_do', `DO $$ BEGIN EXECUTE 'DROP TABLE ${t}'; END $$;`],
 ['cte_delete', `WITH gone AS (DELETE FROM "${t}" RETURNING *) SELECT * FROM gone`],
 ['unknown_tail', `CREATE TABLE IF NOT EXISTS harmless(id int); VACUUM "${t}"`],
 ['drop_schema', `DROP SCHEMA public CASCADE`],
 ['replace_function', `CREATE OR REPLACE FUNCTION f() RETURNS void LANGUAGE sql AS $$DELETE FROM "${t}"$$`],
];
const rows = [];
for (const t of tables) for (const [sample, sql] of samples(t)) {
 test(`${t}: ${sample}`, () => {
   const report = classifyMigration(sql);
   assert.equal(report.summary.blocked, true, sql);
   assert.throws(() => assertSafeMigration(sql), /BLOCKED/);
   rows.push({ sample, protected_table:t, expected:'BLOCK', actual:report.findings.map(f=>f.kind).join('|'), blocked:'yes', sql });
 });
}
test('all targets and ALTER actions are represented', () => {
 const {summary,findings} = classifyMigration('DROP TABLE paper_trades, trading_universes; ALTER TABLE trading_universe_members ADD COLUMN x text, DROP COLUMN evidence, DROP CONSTRAINT y;');
 assert.deepEqual(summary.protectedAtRisk,['paper_trades','trading_universes','trading_universe_members']);
 assert.equal(findings.length,5);
});
test('unknown, malformed and procedural SQL fail closed', () => {
 for (const sql of ['SELECT dangerous()', '/* unterminated', "SELECT 'broken", 'DO $$ broken', 'ALTER TABLE trading_universes ENABLE TRIGGER ALL', 'CREATE TABLE IF NOT EXISTS x(a text DEFAULT dangerous())', 'CREATE TABLE x AS SELECT dangerous()', 'SET standard_conforming_strings = off', 'CREATE INDEX IF NOT EXISTS x ON trading_universes (dangerous(id))']) {
  assert.throws(()=>assertSafeMigration(sql), /BLOCKED/);
 }
});
test('simple additive grammar is allowed', () => {
 for (const sql of ['CREATE TABLE IF NOT EXISTS x(id int)', 'CREATE INDEX IF NOT EXISTS x ON trading_universes (id)', 'ALTER TABLE trading_universes ADD COLUMN IF NOT EXISTS x text, ADD COLUMN y jsonb']) assertSafeMigration(sql);
});
test('exact Task964 migration and reviewed function/trigger bodies are allowed', () => {
 const sql = fs.readFileSync(new URL('migrations/0002_universe_authority_schema_parity.sql',root),'utf8');
 assertSafeMigration(sql);
 for (const m of sql.matchAll(/EXECUTE \$function\$([\s\S]*?)\$function\$/g)) assertSafeMigration(m[1].trim());
 // A changed procedural body is not approved simply because it starts with DO.
 assert.throws(()=>assertSafeMigration(sql.replace('RETURN NEW;', 'DELETE FROM trading_universes; RETURN NEW;')), /BLOCKED/);
});
test('lexer preserves dollar bodies and quoted semicolons', () => {
 assert.equal(splitSqlStatements(`DO $$ BEGIN RAISE NOTICE 'x;y'; END $$; SELECT 'a;b';`).length,2);
});
test('CLI blocks original bypass families without any database connection', () => {
 const dir=fs.mkdtempSync(path.join(os.tmpdir(),'task967-guard-'));
 const cli=fileURLToPath(new URL('./safe-migrate.mjs',import.meta.url));
 try {
  for(const t of tables.filter(t=>t.startsWith('trading_universe')||t==='runtime_universe_session_pins')) {
   for(const [,sql] of samples(t).filter(([id])=>['multi_drop','compound_alter','multiple'].includes(id))) {
    const f=path.join(dir,'sample.sql');fs.writeFileSync(f,sql);
    const result=spawnSync(process.execPath,[cli,'check',f],{encoding:'utf8',env:{...process.env,DATABASE_URL:'postgresql://127.0.0.1:1/never_connect',SAFE_MIGRATE_CONFIRM:'I HAVE A VERIFIED BACKUP AND APPROVE DESTRUCTIVE MIGRATION'}});
    assert.equal(result.status,2,result.stderr);assert.match(result.stderr,/BLOCKED/);
   }
  }
 } finally {fs.rmSync(dir,{recursive:true});}
});
process.on('exit',()=>{
 if(process.env.TASK967_MATRIX){
  const keys=['sample','protected_table','expected','actual','blocked','sql'];
  const csv=[keys.join(','),...rows.map(r=>keys.map(k=>'"'+r[k].replaceAll('"','""')+'"').join(','))].join('\n')+'\n';
  fs.writeFileSync(process.env.TASK967_MATRIX,csv);
 }
});
