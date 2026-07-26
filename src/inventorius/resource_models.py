from flask import Response, url_for
import json
from inventorius.db import db
from inventorius.holding_queries import locations_for_batch
from inventorius.data_models import DataModel, DataModelJSONEncoder, Batch, Bin
import inventorius.resource_operations as operations
from inventorius.auth import current_actor


def _resource_operations(capability, *items):
    """Keep safe links public and mutation affordances caller-truthful."""
    actor = current_actor()
    return [
        item
        for item in items
        if item["method"] == "GET" or actor.can(capability)
    ]

# operation = {
#   "rel": operation name (resource method),
#   "method": GET | POST |PUT|DELETE|PATCH
#   "href": uri,
#   (Expects-a): type or schema
# }


class BlankEncoder(json.JSONEncoder):
    """Without this blank encoder the 'dumps' in problem_response and get_response throws error when encountering unserializable types."""
    def default(self, o):
        return {}


class HypermediaEndpoint:
    def __init__(self, resource_uri=None, state=None, operations=None):
        self.resource_uri = resource_uri
        self.state = state
        self.operations = operations

    def get_response(self, status_code=200, mimetype="application/json"):
        resp = Response()
        resp.status_code = status_code
        resp.mimetype = mimetype

        data = {}
        if self.resource_uri is not None:
            data["Id"] = self.resource_uri
        if self.state is not None:
            if isinstance(self.state, DataModel):
                data["state"] = self.state.to_dict(mask_default=True)
            else:
                data["state"] = self.state
        if self.operations is not None:
            data["operations"] = self.operations

        resp.data = json.dumps(data, cls=BlankEncoder)
        return resp

    def redirect_response(self, redirect=True):
        if redirect:
            raise NotImplementedError()
        resp = Response()
        resp.status_code = 200
        resp.mimetype = "application/json"
        resp.data = json.dumps({"Id": self.resource_uri})
        return resp

    def status_response(self, status_message="ok", status_code=200):
        resp = Response()
        resp.status_code = status_code
        resp.mimetype = "application/json"
        resp.data = json.dumps(
            {"Id": self.resource_uri, "status": status_message})
        return resp


class BatchEndpoint(HypermediaEndpoint):
    @classmethod
    def from_batch(cls, data_batch: Batch):
        endpoint = BatchEndpoint(
            resource_uri=url_for("batch.batch_get", id=data_batch.id),
            state=data_batch.to_dict(mask_default=True),
            operations=_resource_operations(
                "catalog.mutate",
                operations.batch_update(data_batch.id),
                operations.batch_delete(data_batch.id),
                operations.batch_bins(data_batch.id),
            ),
        )
        endpoint.data_batch = data_batch
        return endpoint

    @classmethod
    def from_id(cls, batch_id: str, retrieve=False):
        if retrieve:
            raise NotImplementedError()

        endpoint = BatchEndpoint(
            resource_uri=url_for("batch.batch_get", id=batch_id),
            operations=_resource_operations(
                "catalog.mutate",
                operations.batch_update(batch_id),
                operations.batch_delete(batch_id),
                operations.batch_bins(batch_id),
            ),
        )
        return endpoint

    def created_success_response(self):
        return self.status_response("batch created", status_code=201)

    def updated_success_response(self):
        return self.status_response("batch updated")

    def deleted_success_response(self):
        return self.status_response("batch deleted")


class BatchBinsEndpoint(HypermediaEndpoint):
    @classmethod
    def from_id(cls, batch_id, retrieve=False):
        if not retrieve:
            raise NotImplementedError()

        locations = locations_for_batch(batch_id)

        endpoint = BatchBinsEndpoint(
            resource_uri=url_for("batch.batch_bins_get", id=batch_id),
            state=locations
        )
        return endpoint


class BinEndpoint(HypermediaEndpoint):
    @classmethod
    def from_bin(cls, bin):
        endpoint = BinEndpoint(
            resource_uri=url_for("bin.bin_get", id=bin.id),
            state=bin.to_dict(),
            operations=_resource_operations(
                "catalog.mutate",
                operations.bin_update(bin.id),
                operations.bin_delete(bin.id),
            )
        )
        return endpoint

    def created_success_response(self):
        return self.status_response("bin created", status_code=201)

    def updated_success_response(self):
        return self.status_response("bin updated")

    def deleted_success_response(self):
        return self.status_response("bin deleted")


class SkuEndpoint(HypermediaEndpoint):
    @classmethod
    def from_sku(cls, sku):
        endpoint = SkuEndpoint(
            resource_uri=url_for("sku.sku_get", id=sku.id),
            state=sku.to_dict(),
            operations=_resource_operations(
                "catalog.mutate",
                operations.sku_update(sku.id),
                operations.sku_delete(sku.id),
                operations.sku_bins(sku.id),
                operations.sku_batches(sku.id),
            )
        )
        return endpoint

    def created_success_response(self):
        return self.status_response("sku created", status_code=201)

    def updated_success_response(self):
        return self.status_response("sku updated")

    def deleted_success_response(self):
        return self.status_response("sku deleted")


class ProcessDefinitionEndpoint(HypermediaEndpoint):
    @classmethod
    def from_state(cls, state, mutable=True):
        process_id = state["id"]
        resource_operations = [operations.process_definition_revisions(process_id)]
        if mutable and current_actor().can("catalog.mutate"):
            resource_operations = [
                operations.process_definition_update(process_id),
                operations.process_definition_delete(process_id),
                *resource_operations,
            ]
        return cls(
            resource_uri=url_for(
                "process_definition.process_definition_get",
                id=process_id,
            ),
            state=state,
            operations=resource_operations,
        )

    def created_success_response(self):
        return self.status_response("process definition created", status_code=201)

    def updated_success_response(self):
        return self.status_response("process definition updated")

    def deleted_success_response(self):
        return self.status_response("process definition deleted")


class StatusEndpoint(HypermediaEndpoint):
    def __init__(
        self,
        version,
        is_up=True,
        db_connected=None,
        build_id=None,
        component=None,
        revision=None,
        product_release=None,
        environment=None,
    ):
        state = {
            "version": version,
            "is-up": is_up,
        }
        if db_connected is not None:
            state["db-connected"] = db_connected
        if build_id is not None:
            state["build-id"] = build_id
        if component is not None:
            state["component"] = component
        if revision is not None:
            state["revision"] = revision
        if product_release is not None:
            state["product-release"] = product_release
        if environment is not None:
            state["environment"] = environment
        super().__init__(resource_uri=url_for("get_version"), state=state)
