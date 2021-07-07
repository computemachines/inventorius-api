import fetch from "cross-fetch";
import { json } from "express";
import { stringify } from "querystring";
import { createContext } from "react";

import {
  Bin,
  RestOperation,
  CallableRestOperation,
  NextBin,
  Problem,
  Sku,
  SearchResults,
  NextSku,
  NextBatch,
} from "./data-models";

export interface FrontloadContext {
  api: InventoryApi;
}

export class InventoryApi {
  hostname: string;
  constructor(hostname = "") {
    this.hostname = hostname;
  }

  hydrate<T extends Sku>(server_rendered: T): T {
    if (Object.getPrototypeOf(server_rendered) !== Object.prototype)
      return server_rendered;
    switch (server_rendered.kind) {
      case "sku":
        Object.setPrototypeOf(server_rendered, Sku.prototype);
        break;
      default:
        let _exhaustive_check: never;
    }
    for (const key in server_rendered.operations) {
      Object.setPrototypeOf(
        server_rendered.operations[key],
        CallableRestOperation.prototype
      );
      server_rendered.operations[key].hostname = this.hostname;
    }
    return server_rendered;
  }

  async getVersion(): Promise<string> {
    return (await fetch(`${this.hostname}/api/version`)).text();
  }
  async getNextBin(): Promise<NextBin | Problem> {
    const resp = await fetch(`${this.hostname}/api/next/bin`);
    const json = await resp.json();
    if (!resp.ok) return { ...json, kind: "problem" };
    return new NextBin({ ...json, hostname: this.hostname });
  }
  async getNextSku(): Promise<NextSku | Problem> {
    const resp = await fetch(`${this.hostname}/api/next/sku`);
    const json = await resp.json();
    if (!resp.ok) return { ...json, kind: "problem" };
    return new NextSku({ ...json, hosthame: this.hostname });
  }
  async getNextBatch(): Promise<NextBatch | Problem> {
    const resp = await fetch(`${this.hostname}/api/next/batch`);
    const json = await resp.json();
    if (!resp.ok) return { ...json, kind: "problem" };
    return new NextBatch({ ...json, hostname: this.hostname });
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
  newSku(params: {
    id: string;
    name: string;
    props?: unknown;
    owned_codes?: string[];
    associated_codes?: string[];
  }): Promise<Response> {
    return fetch(`${this.hostname}/api/skus`, {
      method: "POST",
      body: JSON.stringify(params),
      headers: {
        "Content-Type": "application/json",
      },
    });
  }
  newBatch(params: {
    id: string;
    sku_id?: string;
    name?: string;
    owned_codes?: string[];
    associated_codes?: string[];
    props?: unknown;
  }): Promise<Response> {
    return fetch(`${this.hostname}/api/batches`, {
      method: "POST",
      body: JSON.stringify(params),
      headers: {
        "Content-Type": "application/json",
      },
    });
  }
  // async getSku
}

// Do not use this on the server side! Use react-frontload.
export const ApiContext = createContext<InventoryApi>(new InventoryApi(""));
