import fetch from "cross-fetch";

type Props = unknown;

export interface Problem {
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
      return fetch(`${this.hostname}/${this.href}`, {
        method: this.method,
        body,
      });
    } else if (json) {
      return fetch(`${this.hostname}/${this.href}`, {
        method: this.method,
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify(json),
      });
    } else {
      return fetch(`${this.hostname}/${this.href}`, {
        method: this.method,
      });
    }
  }
}

export class Bin extends RestEndpoint {
  kind: "bin" = "bin";
  state: {
    id: string;
    contents: Record<string, number>;
    props?: Props;
  };
  operations: {
    delete: CallableRestOperation;
    update: CallableRestOperation;
  };

  update(props: Props): Promise<Response> {
    return this.operations.update.perform({ json: { props: props } });
  }

  delete(): Promise<Response> {
    return this.operations.delete.perform();
  }
}

type BinId = string;
type SkuId = string;
type BatchId = string;
interface SkuLocations {
  kind: "sku-locations";
  state: Record<BinId, Record<SkuId, number>>;
}
interface SkuBatches {
  kind: "sku-batches";
  state: BatchId[];
}

export class Sku extends RestEndpoint {
  kind: "sku" = "sku";
  state: {
    id: string;
    owned_codes: string[];
    associated_codes: string[];
    name?: string;
    props?: Props;
  };
  operations: {
    update: CallableRestOperation;
    delete: CallableRestOperation;
    bins: CallableRestOperation;
    batches: CallableRestOperation;
  };
  update(patch: {
    owned_codes?: string[];
    associated_codes?: string[];
    props: Props;
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
