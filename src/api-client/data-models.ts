import fetch from "cross-fetch";

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

export class Bin implements RestEndpoint {
  constructor(
    public state: {
      id: string;
      contents: Record<string, number>;
      props?: Record<string, unknown>;
    },
    public operations: {
      delete: CallableRestOperation;
      update: CallableRestOperation;
    }
  ) {}

  update(props: Record<string, unknown>): Promise<Response> {
    return this.operations.update.perform({ body: JSON.stringify({ props }) });
  }

  delete(): Promise<Response> {
    return this.operations.delete.perform();
  }
}

export class NextBin extends RestEndpoint {
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
//   props?: Record<string, unknown>;
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
//   props?: Record<string, unknown>;
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
