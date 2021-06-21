import fetch from "cross-fetch";
import { stringify } from "querystring";

import {
  Bin,
  RestOperation,
  CallableRestOperation,
  NextBin,
  Problem,
  Sku,
  SearchResults,
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
  async getSearchResults(params: {
    query: string;
    limit?: number;
    startingFrom?: number;
  }): Promise<SearchResults | Problem> {
    const resp = await fetch(
      `${this.hostname}/api/search?${stringify(params)}`
    );
    const json = await resp.json();

    if (resp.ok) return new SearchResults({ ...json });
    else return { ...json, kind: "problem" };
  }
  async getBin(id: string): Promise<Bin | Problem> {
    const resp = await fetch(`${this.hostname}/api/bin/${id}`);
    const json = await resp.json();

    if (resp.ok) return new Bin({ ...json, hostname: this.hostname });
    else return { ...json, kind: "problem" };
  }
  newBin({ id, props }: { id: string; props: unknown }): Promise<Response> {
    return fetch(`${this.hostname}/api/bins`, {
      method: "POST",
      body: JSON.stringify({ id, props }),
      headers: {
        "Content-Type": "application/json",
      },
    });
  }
  async getSku(id: string): Promise<Sku | Problem> {
    const resp = await fetch(`${this.hostname}/api/sku/${id}`);
    const json = await resp.json();
    if (resp.ok) return new Sku({ ...json, hostname: this.hostname });
    else return { ...json, kind: "problem" };
  }
  // async getSku
}
