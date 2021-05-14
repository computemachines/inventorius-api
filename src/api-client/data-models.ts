import fetch from "cross-fetch";

interface RestEndpoint {
  state: Record<string, unknown>;
  operations: Record<string, CallableRestOperation>;
}

export interface RestOperation {
  rel: string;
  href: string;
  method: "GET" | "POST" | "PUT" | "PATCH" | "DELETE";
}
export class CallableRestOperation {
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

  perform({ body }: { body?: string } = {}): Promise<Response> {
    return fetch(`${this.hostname}/${this.href}`, {
      method: this.method,
      body,
    });
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
  ) { }

  update(props: Record<string, unknown>): Promise<Response> {
    return this.operations.update.perform({ body: JSON.stringify({ props }) });
  }

  delete(): Promise<Response> {
    return this.operations.delete.perform();
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
