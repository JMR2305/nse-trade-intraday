// Split PostgreSQL statements without splitting function bodies or quoted text.
// Comments are replaced by whitespace so they cannot masquerade as executable SQL.
// This is a lexer, not a general SQL validator: procedural bodies still require
// review of the complete migration before publication.
export function splitSqlStatements(sql) {
  const result = [];
  let statement = "";
  let i = 0;
  const emit = () => {
    if (statement.trim()) result.push(statement.trim());
    statement = "";
  };
  while (i < sql.length) {
    if (sql.startsWith("--", i)) {
      const end = sql.indexOf("\n", i);
      i = end < 0 ? sql.length : end + 1;
      statement += "\n";
    } else if (sql.startsWith("/*", i)) {
      let depth = 1;
      i += 2;
      while (i < sql.length && depth) {
        if (sql.startsWith("/*", i)) { depth++; i += 2; }
        else if (sql.startsWith("*/", i)) { depth--; i += 2; }
        else i++;
      }
      if (depth) throw new Error("Unterminated SQL block comment");
      statement += " ";
    } else if (sql[i] === "'" || sql[i] === '"') {
      const start = i;
      const quote = sql[i++];
      const escaped = quote === "'" && /(?:^|[^\w])e$/i.test(sql.slice(0, start));
      let closed = false;
      while (i < sql.length) {
        if (escaped && sql[i] === "\\") { i += 2; continue; }
        if (sql[i++] === quote) {
          if (sql[i] === quote) { i++; continue; }
          closed = true;
          break;
        }
      }
      if (!closed) throw new Error("Unterminated SQL quote");
      statement += sql.slice(start, i);
    } else if (sql[i] === "$" && /^(\$[A-Za-z_][A-Za-z_0-9]*\$|\$\$)/.test(sql.slice(i))) {
      const tag = sql.slice(i).match(/^(\$[A-Za-z_][A-Za-z_0-9]*\$|\$\$)/)[0];
      const end = sql.indexOf(tag, i + tag.length);
      if (end < 0) throw new Error("Unterminated SQL dollar quote");
      statement += sql.slice(i, end + tag.length);
      i = end + tag.length;
    } else if (sql[i] === ";") {
      emit();
      i++;
    } else {
      statement += sql[i++];
    }
  }
  emit();
  return result;
}
