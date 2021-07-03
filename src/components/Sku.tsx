import * as React from "react";
import { useFrontload } from "react-frontload";
import { useParams } from "react-router-dom";
import { FrontloadContext } from "../api-client/inventory-api";
import ReactModal from "react-modal";

import "../styles/Sku.css";
import "../styles/warnModal.css";
import CodesInput from "./CodesInput";
import { FourOhFour } from "./FourOhFour";
import ItemLabel from "./ItemLabel";
import PrintButton from "./PrintButton";
import SkuItemLocations from "./SkuItemLocations";

function Sku() {
  const { id } = useParams<{ id: string }>();
  const { data, frontloadMeta } = useFrontload(
    "sku-component",
    async ({ api }: FrontloadContext) => ({
      sku: await api.getSku(id),
    })
  );
  const [showModal, setShowModal] = React.useState(false);

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
          <button className="modal-close">X</button>
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
        <div className="info-item">
          <div className="info-item-title">Name</div>
          <div className="info-item-description">
            {frontloadMeta.done ? data.sku.state.name : "Loading..."}
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
            {frontloadMeta.done ? (
              <CodesInput
                codes={[
                  ...data.sku.state.owned_codes.map((code) => ({
                    kind: "owned" as "owned",
                    value: code,
                  })),
                  ...data.sku.state.associated_codes.map((code) => ({
                    kind: "associated" as "associated",
                    value: code,
                  })),
                ]}
                editable={false}
              />
            ) : (
              "Loading..."
            )}
          </div>
        </div>
        <div className="info-item">
          <div className="info-item-title">Actions</div>
          <div className="info-item-description" style={{ display: "block" }}>
            <a href="#" className="action-link">
              Edit
            </a>
            <a href="#" className="action-link">
              Receive
            </a>
            <a
              href="#"
              className="action-link"
              onClick={() => setShowModal(true)}
            >
              Delete?
            </a>
          </div>
        </div>
      </div>
    );
  }
}
export default Sku;
