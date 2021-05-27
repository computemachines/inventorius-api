import fetch from "cross-fetch";
import {
  Bin,
  RestOperation,
  CallableRestOperation,
  NextBin,
} from "./data-models";

export interface FrontloadContext {
  api: InventoryApi;
}

export class InventoryApi {
  hostname: string;
  constructor(hostname = "") {
    this.hostname = hostname;
  }
  async getVersion(): Promise<string> {
    return (await fetch(`${this.hostname}/api/version`)).text();
  }
  async getNextBin(): Promise<NextBin> {
    const resp = await fetch(`${this.hostname}/api/next/bin`);
    if (!resp.ok) throw resp;
    const json = await resp.json();
    return new NextBin({
      state: json.state,
      operations: json.operations,
      hostname: this.hostname,
    });
  }
  async getBin(id: string): Promise<Bin> {
    const resp = await fetch(`${this.hostname}/api/bin/${id}`);
    // if (!resp.ok) throw resp;
    const json = await resp.json();
    return new Bin({
      state: json.state,
      operations: json.operations,
      hostname: this.hostname,
    });
  }
  async newBin({ id, props }: { id: string; props: unknown }) {}
  // async getSku
}
