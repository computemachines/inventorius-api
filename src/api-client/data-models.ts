import fetch from "cross-fetch";

type Props = Record<string, unknown> | null;

/**
 * JSON representation of a 'application/problem+json' response.
 */
export interface Problem {
  /**
   * Discriminator
   */
  kind: "problem";
  type: string;
  title: string;
  "invalid-params": Array<{ name: string; reason: string }>;
}

class RestEndpoint {
  state: unknown;
  operations: Record<string, CallableRestOperation>;
  constructor({
    state,
    operations,
    hostname,
  }: {
    state: unknown;
    operations: RestOperation[];
    hostname: string;
  }) {
    this.state = state;
    this.operations = {};
    for (const op of operations) {
      this.operations[op.rel] = new CallableRestOperation({ hostname, ...op });
    }
  }
}

export interface RestOperation {
  rel: string;
  href: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
}

export class CallableRestOperation implements RestOperation {
  rel: string;
  href: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
  hostname: string;
  constructor(config: {
    rel: string;
    href: string;
    method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
    hostname: string;
  }) {
    Object.assign(this, config);
  }

  perform({
    body,
    json,
  }: {
    body?: string;
    json?: unknown;
  } = {}): Promise<Response> {
    if (body) {
      return fetch(`${this.hostname}${this.href}`, {
        method: this.method,
        body,
      });
    } else if (json) {
      return fetch(`${this.hostname}${this.href}`, {
        method: this.method,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(json),
      });
    } else {
      return fetch(`${this.hostname}${this.href}`, {
        method: this.method,
      });
    }
  }
}

export interface BinState {
  id: string;
  contents: Record<string, number>;
  props?: Props;
}
export class Bin extends RestEndpoint {
  kind: "bin" = "bin";
  state: BinState;
  operations: {
    delete: CallableRestOperation;
    update: CallableRestOperation;
  };

  update(patch:{props:Props}): Promise<Response> {
    return this.operations.update.perform({ json: patch });
  }

  delete(): Promise<Response> {
    return this.operations.delete.perform();
  }
}

type BinId = string;
type SkuId = string;
type BatchId = string;
export interface SkuLocations {
  kind: "sku-locations";
  state: Record<BinId, Record<SkuId, number>>;
}
interface SkuBatches {
  kind: "sku-batches";
  state: BatchId[];
}
export interface BatchLocations {
  kind: "batch-locations";
  state: Record<BinId, Record<BatchId, number>>;
}

export interface SkuState {
  id: string;
  owned_codes: string[];
  associated_codes: string[];
  name?: string;
  props?: Props;
}
export class Sku extends RestEndpoint {
  kind: "sku" = "sku";
  state: SkuState;
  operations: {
    update: CallableRestOperation;
    delete: CallableRestOperation;
    bins: CallableRestOperation;
    batches: CallableRestOperation;
  };
  update(patch: {
    name?: string;
    owned_codes?: string[];
    associated_codes?: string[];
    props?: Props;
  }): Promise<Response> {
    return this.operations.update.perform({ json: patch });
  }
  delete(): Promise<Response> {
    return this.operations.delete.perform();
  }
  async bins(): Promise<SkuLocations | Problem> {
    const resp = await this.operations.bins.perform();
    const json = await resp.json();
    if (resp.ok) return { ...json, kind: "sku-locations" };
    else return { ...json, kind: "problem" };
  }
  async batches(): Promise<SkuBatches | Problem> {
    const resp = await this.operations.batches.perform();
    const json = await resp.json();
    if (resp.ok) return { ...json, kind: "sku-batches" };
    else return { ...json, kind: "problem" };
  }
}

export interface BatchState {
  id: string;
  sku_id?: string;
  name?: string;
  owned_codes?: string[];
  associated_codes?: string[];
  props?: Props;
}
export class Batch extends RestEndpoint {
  kind: "batch" = "batch";
  state: BatchState;
  operations: {
    update: CallableRestOperation;
    delete: CallableRestOperation;
    bins: CallableRestOperation;
  };
  update(patch: {
    sku_id?: string;
    name?: string;
    owned_codes?: string[];
    associated_codes?: string[];
    props?: Props;
  }): Promise<Response> {
    return this.operations.update.perform({ json: patch });
  }
  delete(): Promise<Response> {
    return this.operations.delete.perform();
  }
  async bins(): Promise<BatchLocations | Problem> {
    const resp = await this.operations.bins.perform();
    const json = await resp.json();
    if (resp.ok) return { ...json, kind: "batch-locations" };
    else return { ...json, kind: "problem" };
  }
}

export class NextBin extends RestEndpoint {
  kind: "next-bin" = "next-bin";
  state: string;
  operations: {
    create: CallableRestOperation;
  };

  create(): Promise<Response> {
    return this.operations.create.perform({ json: { id: this.state } });
  }
}

export class NextSku extends RestEndpoint {
  kind: "next-sku" = "next-sku";
  state: string;
  operations: {
    create: CallableRestOperation;
  };

  create(): Promise<Response> {
    return this.operations.create.perform({ json: { id: this.state } });
  }
}

export class NextBatch extends RestEndpoint {
  kind: "next-batch" = "next-batch";
  state: string;
  operations: {
    create: CallableRestOperation;
  };

  create(): Promise<Response> {
    return this.operations.create.perform({ json: { id: this.state } });
  }
}

export type SearchResult = SkuState | BatchState | BinState;
export class SearchResults extends RestEndpoint {
  kind: "search-results" = "search-results";
  state: {
    total_num_results: number;
    starting_from: number;
    limit: number;
    returned_num_results: number;
    results: SearchResult[];
  };
  operations: null;
}
export function isSkuState(result: SearchResult): result is SkuState {
  return result.id.startsWith("SKU");
}
export function isBinState(result: SearchResult): result is BinState {
  return result.id.startsWith("BIN");
}
export function isBatchState(result: SearchResult): result is BatchState {
  return result.id.startsWith("BAT");
}

// type Sku = {
//   id: string;
//   ownedCodes?: Array<string>;
//   associatedCodes?: Array<string>;
//   name?: string;
//   props?: Props;
// };

// export function Sku(json: Sku): void {
//   this.id = json.id;
//   this.ownedCodes = json.ownedCodes || [];
//   this.associatedCodes = json.associatedCodes || [];
//   this.name = json.name;
//   this.props = json.props;
// }
// Sku.prototype.toJson = null;

// type Batch = {
//   id: string;
//   skuId?: string;
//   ownedCodes?: Array<string>;
//   associatedCodes?: Array<string>;
//   name?: string;
//   props?: Props;
// };

// export function Batch(json: Batch): void {
//   this.id = json.id;
//   this.skuId = json.skuId;
//   this.ownedCodes = json.ownedCodes || [];
//   this.associatedCodes = json.associatedCodes || [];
//   this.name = json.name;
//   this.props = json.props;
// }
// Batch.prototype.toJson = null;
