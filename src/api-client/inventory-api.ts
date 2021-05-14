import fetch from "cross-fetch";
import { Bin, RestOperation, CallableRestOperation } from "./data-models";

export default class InventoryApi {
  hostname: string;
  constructor(hostname = "") {
    this.hostname = hostname;
  }
  async getVersion(): Promise<string> {
    return (await fetch(`${this.hostname}/api/version`)).text();
  }
  async getBin(id: string): Promise<Bin> {
    const resp = await fetch(`${this.hostname}/api/bin/${id}`);
    if (!resp.ok) throw resp;
    const json = await resp.json();
    const state = json.state;
    const operations = json.operations.map(
      (op: RestOperation) =>
        new CallableRestOperation({ hostname: this.hostname, ...op })
    );
    return new Bin(state, operations);
  }
  // async getSku
}
