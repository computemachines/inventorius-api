/**
 * Print a label on the local label printer.
 *
 * @category External Tools
 * @param {string} label - The Label to be printed.
 * @returns {Promise<Response>} A Promise to the response of the api call.
 */
export function printLabel(label) {
  // TODO: Sanitize and/or change print server api
  return fetch(`http://127.0.0.1:8899/print/${label}`);
}
