import * as React from "react";
import { useContext, useEffect, useState } from "react";

import { ApiContext } from "../api-client/api-client";
import { ToastContext } from "./Toast";

import "../styles/form.css";
import { json } from "express";
import ItemLabel from "./ItemLabel";
import { parse, stringifyUrl } from "query-string";
import { generatePath, useHistory, useLocation } from "react-router-dom";

function Release() {
    const location = useLocation();
    const history = useHistory();
    const api = useContext(ApiContext);
    const { setToastContent: setAlertContent } = useContext(ToastContext);

    const [fromIdValue, setFromIdValue] = useState("");
    const [itemIdValue, setItemIdValue] = useState("");
    const [quantityValue, setQuantityValue] = useState("1");

    useEffect(() => {
        const queryParams = parse(location.search);

        if (queryParams["from"]) {
            setFromIdValue(queryParams["from"] as string);
        }
        if (queryParams["item"]) {
            setItemIdValue(queryParams["item"] as string);
        }
        if (queryParams["quantity"]) {
            setQuantityValue(queryParams["quantity"] as string);
        }

    }, [location.search]);

    return (
        <form
            className="form"
            onSubmit={async (e) => {
                e.preventDefault();

                const resp = await api.release({
                    from_id: fromIdValue,
                    item_id: itemIdValue,
                    quantity: parseInt(quantityValue),
                });
                if (resp.kind == "status") {
                    setAlertContent({
                        content: (
                            <div>
                                Success, Released {quantityValue} count,{" "}
                                <ItemLabel label={itemIdValue} onClick={(e) => setAlertContent({})} />
                                , from{" "}
                                <ItemLabel label={fromIdValue} />
                            </div>
                        ),
                        mode: "success"
                    });

                    setFromIdValue("");
                    setItemIdValue("");
                    setQuantityValue("1");
                    if (location.search) history.push("/release");
                } else {
                    setAlertContent({
                        content: <div>{resp.title}</div>,
                        mode: "failure"
                    });
                }
            }} >
            <h2 className="form-title">Release</h2>
            <label htmlFor="from_id" className="form-label">Bin Label</label>
            <input
                type="text"
                className="form-single-code-input"
                id="from_id"
                name="from_id"
                value={fromIdValue}
                onChange={(e) => setFromIdValue(e.target.value)} />
            <label htmlFor="item_id" className="form-label">
                Item Label
            </label>
            <input
                type="text"
                name="item_id"
                id="item_id"
                className="form-single-code-input"
                value={itemIdValue}
                onChange={(e) => setItemIdValue(e.target.value)}
            />
            <label htmlFor="quantity" className="form-label">
                Quantity
            </label>
            <input
                type="number"
                name="quantity"
                id="quantity"
                className="form-single-code-input"
                value={quantityValue}
                onChange={(e) => setQuantityValue(e.target.value)}
            />

            <input type="submit" value="Submit" className="form-submit" />
        </form>
    )
}
export default Release;