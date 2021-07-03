import * as React from "react";
import { useFrontload } from "react-frontload";
import { generatePath, useHistory, useParams } from "react-router-dom";
import { FrontloadContext } from "../api-client/inventory-api";
import ReactModal from "react-modal";
import { Link } from "react-router-dom";

import "../styles/Sku.css";
import "../styles/infoPanel.css";
import "../styles/warnModal.css";
import CodesInput from "./CodesInput";
import { FourOhFour } from "./FourOhFour";
import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";
import SkuItemLocations from "./SkuItemLocations";
import { useContext } from "react";
import { AlertContext } from "./Alert";

function Sku({ editable = false }: { editable?: boolean }) {
  const { id } = useParams<{ id: string }>();
  const { data, frontloadMeta } = useFrontload(
    "sku-component",
    async ({ api }: FrontloadContext) => ({
      sku: await api.getSku(id),
    })
  );
  const { setAlertContent } = useContext(AlertContext);
  const [showModal, setShowModal] = React.useState(false);
  const [unsavedChanges, setUnsavedChanges] = React.useState(false);
  const history = useHistory();
  const [unsavedName, setUnsavedName] = React.useState("");
  const [unsavedCodes, setUnsavedCodes] = React.useState([]);

  React.useEffect(() => {
    if (frontloadMeta.done && data.sku.kind != "problem") {
      setUnsavedName(data.sku.state.name);
      setUnsavedCodes([
        ...data.sku.state.owned_codes.map((code) => ({
          kind: "owned" as "owned",
          value: code,
        })),
        ...data.sku.state.associated_codes.map((code) => ({
          kind: "associated" as "associated",
          value: code,
        })),
      ]);
    }
  }, [frontloadMeta]);

  if (data?.sku.kind == "problem") {
    if (data.sku.type == "missing-resource") return <FourOhFour />;
    else return <h2>{data.sku.title}</h2>;
  } else {
    if (frontloadMeta.error) {
      return <div>Connection Error</div>;
    }

    return (
      <div className="info-panel">
        <ReactModal isOpen={showModal} className="warn-modal">
          <button className="modal-close" onClick={() => setShowModal(false)}>
            X
          </button>
          <h3>Are you sure?</h3>
          <button onClick={() => setShowModal(false)}>Cancel</button>
          <button className="button-danger">Delete</button>
        </ReactModal>
        <div className="info-item">
          <div className="info-item-title">Sku Label</div>
          <div className="info-item-description">
            <ItemLabel link={false} label={id} />
            <PrintButton value={id} />
          </div>
        </div>
        {frontloadMeta.pending ? (
          "Loading..."
        ) : (
          <>
            <div className="info-item">
              <div className="info-item-title">Name</div>
              <div className="info-item-description">
                {editable ? (
                  <input
                    className="item-description-oneline"
                    value={unsavedName}
                    onChange={(e) => {
                      setUnsavedChanges(true);
                      setUnsavedName(e.target.value);
                    }}
                  />
                ) : (
                  <div className="item-description-oneline">{unsavedName}</div>
                )}
              </div>
            </div>
            <div className="info-item">
              <div className="info-item-title">Derived Batches</div>
              <div className="info-item-description">TODO</div>
            </div>
            <div className="info-item">
              <div className="info-item-title">Locations</div>
              <div className="info-item-description">
                <SkuItemLocations sku={data?.sku} />
              </div>
            </div>
            <div className="info-item">
              <div className="info-item-title">Codes</div>
              <div className="info-item-description">
                <CodesInput
                  codes={unsavedCodes}
                  setCodes={(codes) => {
                    setUnsavedChanges(true);
                    setUnsavedCodes(codes);
                  }}
                  editable={editable}
                />
              </div>
            </div>
            {editable ? (
              <button
                className="info-edit-save-button"
                onClick={() => {
                  setAlertContent({
                    content: <div>Saved!</div>,
                    mode: "success",
                  });
                  setUnsavedChanges(false);
                  history.push(generatePath("/sku/:id", { id }));
                }}
              >
                Save
              </button>
            ) : (
              <div className="info-item">
                <div className="info-item-title">Actions</div>
                <div
                  className="info-item-description"
                  style={{ display: "block" }}
                >
                  <Link
                    to={generatePath("/sku/:id/edit", { id })}
                    className="action-link"
                  >
                    Edit
                  </Link>
                  <Link to="#" className="action-link">
                    Receive
                  </Link>
                  <Link
                    to="#"
                    className="action-link"
                    onClick={() => setShowModal(true)}
                  >
                    Delete?
                  </Link>
                </div>
              </div>
            )}{" "}
          </>
        )}
      </div>
    );
  }
}
export default Sku;
