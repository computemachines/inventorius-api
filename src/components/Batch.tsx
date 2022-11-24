import * as React from "react";
import { useContext, useEffect, useState } from "react";
import { useFrontload } from "react-frontload";
import * as Sentry from "@sentry/react";
import {
  generatePath,
  Link,
  Prompt,
  useHistory,
  useParams,
} from "react-router-dom";
import { ApiContext, FrontloadContext } from "../api-client/api-client";
// import { Problem, Sku as ApiSku } from "../api-client/data-models";

import "../styles/infoPanel.css";
import { ToastContext } from "./Toast";
import CodesInput, { Code } from "./CodesInput";
import { FourOhFour } from "./FourOhFour";
import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";
import ItemLocations from "./ItemLocations";
import { stringifyUrl } from "query-string";
import { Problem, Sku, Unit, Unit1 } from "../api-client/data-models";
import PropertiesTable, {
  api_props_from_properties,
  Property,
} from "./PropertiesTable";
import WarnModal from "./WarnModal";

function Batch({ editable = false }: { editable?: boolean }) {
  const history = useHistory();
  const { id: batch_id } = useParams<{ id: string }>();

  const [showModal, setShowModal] = useState(false);
  const [saveState, setSaveState] = useState<"live" | "unsaved" | "saving">(
    "live"
  );
  const [unsavedParentSkuId, setUnsavedParentSkuId] = useState("");
  const [unsavedName, setUnsavedName] = useState("");
  const [unsavedCodes, setUnsavedCodes] = useState<Code[]>([]);
  const [unsavedProperties, setUnsavedProperties] = useState<Property[]>([]);

  const api = useContext(ApiContext);
  const { setToastContent } = useContext(ToastContext);

  const { data, frontloadMeta, setData } = useFrontload(
    "batch-component",
    async ({ api }: FrontloadContext) => {
      const batch = await api.getBatch(batch_id);

      let parentSku: Problem | Sku | null = null;
      if (batch.kind == "problem") {
        parentSku = batch;
      } else if (batch.state.sku_id) {
        parentSku = await api.getSku(batch.state.sku_id);
      }

      const batchBins = batch.kind == "batch" ? await batch.bins() : batch;
      return { batch, parentSku, batchBins };
    }
  );

  useEffect(() => {
    if (!editable) setSaveState("live");
  }, [editable]);

  useEffect(() => {
    if (
      frontloadMeta.done &&
      !frontloadMeta.error &&
      data.batch.kind != "problem" &&
      saveState == "live"
    ) {
      // reset unsaved data
      setUnsavedName(data.batch.state.name);
      setUnsavedCodes([
        ...(data.batch.state.owned_codes || []).map((value) => ({
          value,
          kind: "owned" as const,
        })),
        ...(data.batch.state.associated_codes || []).map((value) => ({
          value,
          kind: "associated" as const,
        })),
      ]);
      setUnsavedProperties(
        Object.entries(data.batch.state.props || {}).map(([name, value]) => {
          let typed;
          if (typeof value == "undefined") {
            throw new Error("Api returned empty property: " + name);
          }
          if (typeof value == "number") {
            typed = {
              kind: "number",
              value: value,
            };
          } else if (typeof value == "string") {
            typed = {
              kind: "string",
              value: value,
            };
          } else if (typeof value == "object") {
            if ("unit" in value && "value" in value) {
              const physical = new Unit1(
                value as { unit: string; value: number }
              );
              switch (physical.unit) {
                case "USD":
                  typed = { kind: "currency", value: physical.value };
                  break;

                default:
                  throw new Error("Unsupported api unit type");
              }
            }
          } else {
            throw new Error("Unsupported api type");
          }
          return new Property({ name, typed: typed });
        })
      );
    }
  }, [frontloadMeta, data, saveState]);

  // useEffect(() => {});

  if (frontloadMeta.pending) return <div>Loading...</div>;
  if (frontloadMeta.error) {
    Sentry.captureException(new Error("frontloadMeta.error"));
    return <div>Connection Error</div>;
  }
  if (data.batch.kind == "problem") {
    if (data.batch.type == "missing-resource") {
      Sentry.captureException(new Error("missing batch"));
      return <FourOhFour />;
    } else {
      Sentry.captureException(new Error(JSON.stringify(data)));
      return <div>{data.batch.title}</div>;
    }
  }

  let parentSkuShowItemDesc = null;
  if (editable) {
    parentSkuShowItemDesc = (
      <input
        type="text"
        id="parent_sku_id"
        name="parent_sku_id"
        className="form-single-code-input"
        value={unsavedParentSkuId}
        onChange={(e) => setUnsavedParentSkuId(e.target.value)}
      />
    );
  } else if (!data.batch.state.sku_id) {
    parentSkuShowItemDesc = (
      <div style={{ fontStyle: "italic" }}>(Anonymous)</div>
    );
  } else if (!data.parentSku || data.parentSku.kind == "problem") {
    Sentry.captureException(
      new Error(
        "parent_sku was null or problem but batch.state.sku_id was not empty"
      )
    );
    parentSkuShowItemDesc = <div>{data.batch.state.sku_id} not found</div>;
  } else if (data.parentSku.kind == "sku") {
    parentSkuShowItemDesc = (
      <ItemLabel link={true} label={data.parentSku.state.id} />
    );
  } else {
    throw Error("impossible fallthrough");
  }

  let itemLocations = null;
  if (data.batchBins.kind == "problem") {
    Sentry.captureException(new Error("Error loading batch locations"));
    itemLocations = <div>Problem loading locations</div>;
  } else {
    itemLocations = <ItemLocations itemLocations={data.batchBins} />;
  }

  return (
    <div className="info-panel">
      <Prompt
        message="Leave without saving changes?"
        when={saveState != "live"}
      />
      <WarnModal
        showModal={showModal}
        setShowModal={setShowModal}
        dangerousActionName="Delete"
        onContinue={async () => {
          if (1 == 1) return;
          if (data.batch.kind == "problem") throw "impossible";
          const resp = await api.hydrate(data.batch).delete();
          // setShowModal(false); // this doesn't seem to be necessary?
          if (resp.kind == "status") {
            setToastContent({ content: <p>Deleted</p>, mode: "success" });
            const updatedBatch = await api.getBatch(batch_id);
            const updatedParentSku =
              updatedBatch.kind == "batch"
                ? await api.getSku(updatedBatch.state.sku_id)
                : null;
            const updatedBatchBins =
              updatedBatch.kind == "batch" ? await updatedBatch.bins() : null;
            setData(() => ({
              batch: updatedBatch,
              parentSku: updatedParentSku,
              batchBins: updatedBatchBins,
            }));
          } else {
            setToastContent({
              content: <p>{resp.title}</p>,
              mode: "failure",
            });
          }
        }}
      ></WarnModal>
      <div className="info-panel__item">
        <div className="info-panel__item-title">Parent Sku</div>
        <div className="info-panel__item-description">
          {parentSkuShowItemDesc}
        </div>
      </div>
      <div className="info-panel__item">
        <div className="info-panel__item-title">Batch Label</div>
        <div className="info-panel__item-description">
          <ItemLabel link={false} label={batch_id} />
          <PrintButton value={batch_id} />
        </div>
      </div>
      <div className="info-panel__item">
        <div className="info-panel__item-title">Name</div>
        <div className="info-panel__item-description">
          {editable ? (
            <input
              type="text"
              id="parent_sku_id"
              name="parent_sku_id"
              className="form-single-code-input"
              value={unsavedName}
              onChange={(e) => setUnsavedName(e.target.value)}
            />
          ) : (
            unsavedName || <div style={{ fontStyle: "italic" }}>(Empty)</div>
          )}
        </div>
      </div>
      <div className="info-panel__item">
        <div className="info-panel__item-title">Locations</div>
        <div className="info-panel__item-description">{itemLocations}</div>
      </div>
      <div className="info-panel__item">
        <div className="info-panel__item-title">Codes</div>
        <div className="info-panel__item-description">
          {unsavedCodes.length == 0 && !editable ? (
            "None"
          ) : (
            <CodesInput
              codes={unsavedCodes}
              setCodes={(codes) => {
                setSaveState("unsaved");
                setUnsavedCodes(codes);
              }}
              editable={editable}
            />
          )}
        </div>
      </div>
      <div className="info-panel__item">
        <div className="info-panel__item-title">Additional Properties</div>
        <div className="info-panel__item-description">
          {unsavedProperties.length == 0 && !editable ? (
            "None"
          ) : (
            <PropertiesTable
              editable={editable}
              properties={unsavedProperties}
              setProperties={(properties) => {
                setSaveState("unsaved");
                setUnsavedProperties(properties);
              }}
            />
          )}
        </div>
      </div>
      <div className="info-panel__item">
        <div className="info-panel__item-title">Actions</div>
        <div
          className="info-panel__item-description"
          style={{ display: "block" }}
        >
          {editable ? (
            <div className="edit-controls">
              <button
                className="edit-controls-cancel-button"
                onClick={(e) => {
                  history.push(generatePath("/batch/:id", { id: batch_id }));
                }}
              >
                Cancel
              </button>
              <button
                className="edit-controls-save-button"
                onClick={async () => {
                  if (data.batch.kind == "problem") throw "impossible";
                  setSaveState("saving");
                  console.log(unsavedCodes);
                  const resp = await api.hydrate(data.batch).update({
                    sku_id: unsavedParentSkuId || null,
                    id: batch_id,
                    name: unsavedName,
                    owned_codes: unsavedCodes
                      .filter(({ kind, value }) => kind == "owned" && value)
                      .map(({ value }) => value),
                    associated_codes: unsavedCodes
                      .filter(
                        ({ kind, value }) => kind == "associated" && value
                      )
                      .map(({ value }) => value),
                    props: api_props_from_properties(unsavedProperties),
                  });

                  if (resp.kind == "problem") {
                    Sentry.captureException(
                      new Error("error saving batch edit")
                    );
                    setSaveState("unsaved");
                    setToastContent({
                      content: <p>{resp.title}</p>,
                      mode: "failure",
                    });
                  } else {
                    setSaveState("live");
                    setToastContent({
                      content: <div>Saved!</div>,
                      mode: "success",
                    });
                    const updatedBatch = await api.getBatch(batch_id);
                    const updatedParentSku =
                      updatedBatch.kind == "batch" && updatedBatch.state.sku_id
                        ? await api.getSku(updatedBatch.state.sku_id)
                        : null;
                    const updatedBatchBins =
                      updatedBatch.kind == "batch"
                        ? await updatedBatch.bins()
                        : null;
                    setData((old) => ({
                      ...old,
                      batch: updatedBatch,
                      parentSku: updatedParentSku,
                      batchBins: updatedBatchBins,
                    }));
                    history.push(generatePath("/batch/:id", { id: batch_id }));
                  }
                }}
              >
                {saveState == "saving" ? "Saving..." : "Save"}
              </button>
            </div>
          ) : (
            <>
              <Link
                to={generatePath("/batch/:id/edit", { id: batch_id })}
                className="action-link"
              >
                Edit
              </Link>
              <Link
                to={stringifyUrl({
                  url: "/receive",
                  query: { item: batch_id },
                })}
                className="action-link"
              >
                Receive
              </Link>
              <Link
                to={stringifyUrl({
                  url: "/release",
                  query: { item: batch_id },
                })}
                className="action-link"
              >
                Release
              </Link>
              <Link
                to="#"
                className="action-link"
                onClick={() => setShowModal(true)}
              >
                Delete?
              </Link>
            </>
          )}
        </div>
      </div>
    </div>
  );
}
export default Batch;
