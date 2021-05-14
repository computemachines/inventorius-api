export function printLabel(label) {
  // TODO: Sanitize and/or change print server api
  return fetch(`http://127.0.0.1:8899/print/${label}`);
}
