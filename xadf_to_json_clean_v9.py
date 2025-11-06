import streamlit as st
import xml.etree.ElementTree as ET
import json
import pandas as pd
import plotly.express as px

# ---------- helpers ----------
ELEMENTS = {i:s for i,s in enumerate((
"H","He","Li","Be","B","C","N","O","F","Ne","Na","Mg","Al","Si","P","S","Cl","Ar",
"K","Ca","Sc","Ti","V","Cr","Mn","Fe","Co","Ni","Cu","Zn","Ga","Ge","As","Se","Br","Kr",
"Rb","Sr","Y","Zr","Nb","Mo","Tc","Ru","Rh","Pd","Ag","Cd","In","Sn","Sb","Te","I","Xe",
"Cs","Ba","La","Ce","Pr","Nd","Pm","Sm","Eu","Gd","Tb","Dy","Ho","Er","Tm","Yb","Lu",
"Hf","Ta","W","Re","Os","Ir","Pt","Au","Hg","Tl","Pb","Bi","Po","At","Rn","Fr","Ra","Ac",
"Th","Pa","U"
), start=1)}
LINE_MAP = {3:"K_alpha1",4:"K_alpha2",5:"K_beta2",6:"K_beta1",8:"K_beta3",9:"K_beta5",
            12:"L_alpha1",14:"L_beta1",15:"L_beta2",17:"L_gamma1"}
ATMOSPHERE_MAP = {"0":"Vacuum","1":"Air","2":"Helium"}

def translate_used_lines(s):
    if not s: return []
    try: return [LINE_MAP.get(int(x),f"Line{x}") for x in s.split(",") if x.strip()]
    except: return []

def element_to_dict(elem):
    d={}
    for c in elem:
        if c.tag=="ClassInstance":
            for sub in c: d[sub.tag]=element_to_dict(sub)
            continue
        d[c.tag]=element_to_dict(c) if len(c) else (c.text.strip() if c.text else None)
    return d

def parse_xadf(root):
    data = {}

    # --- Info ---
    info = root.find(".//ClassInstance[@Type='TXS2_XADFMgr_Info']")
    if info is not None:
        data["Info"] = element_to_dict(info)

    # --- Measurement parameters ---
    m = root.find(".//ClassInstance[@Type='TXS2_XADFMgr_MParam']")
    mdata = {}
    if m is not None:
        mdata = element_to_dict(m).get("MParam", {})
        # Tube element symbol
        tube_z = mdata.get("TubeZ")
        if tube_z and tube_z.isdigit():
            mdata["TubeElement"] = ELEMENTS.get(int(tube_z), "?")
        # Atmosphere
        atm = mdata.get("Atmosphere")
        if atm in ATMOSPHERE_MAP:
            mdata["AtmosphereName"] = ATMOSPHERE_MAP[atm]
    data["MeasurementParameters"] = mdata

    # --- Calculation parameters ---
    calc = root.find(".//ClassInstance[@Type='TXS2_XADFMgr_CalcParam']")
    if calc is not None:
        data["CalculationParameters"] = element_to_dict(calc).get("CalculationParameters", {})

    # --- Global elements (with PE_Spc_Number + EmissionLines) ---
    element_lookup = {}
    for i, e in enumerate(root.findall(".//ClassInstance[@Type='TXS2_XADFMgr_SingleElement']")):
        ed = element_to_dict(e)
        se = next(iter(ed.values())) if ed else {}

        # Element symbol from Z
        z = se.get("Z")
        if z and z.isdigit():
            se["ElementSymbol"] = ELEMENTS.get(int(z), "?")

        # Extract PE_Spc_Number from any nested "SingleLine_x" dict
        pe_num = None
        for v in se.values():
            if isinstance(v, dict) and "PE_Spc_Number" in v:
                pe_num = v["PE_Spc_Number"]
                break
        if pe_num is not None:
            se["PE_Spc_Number"] = pe_num

        # Translate emission lines from UsedLines → EmissionLines
        for k, v in se.items():
            if isinstance(v, dict) and "UsedLines" in v:
                v["EmissionLines"] = translate_used_lines(v["UsedLines"])

        element_lookup[i] = se

    data["Elements"] = list(element_lookup.values())

    # --- Layers with embedded element info (incl. PE_Spc_Number) ---
    layers = []
    for i, lyr in enumerate(root.findall(".//ClassInstance[@Type='TXS2_XADFMgr_SingleLayer']"), 1):
        L = element_to_dict(lyr)
        d = next(iter(L.values())) if L else {}
        if not d:
            continue

        layer_info = {
            "Index": i,
            "Description": d.get("Description"),
            "Thickness_um": d.get("Thickness"),
            "Density_gcm3": d.get("Density", {}).get("Default") if isinstance(d.get("Density"), dict) else d.get("Density"),
            "Elements": []
        }

        for k, v in d.items():
            if k.startswith("Element_") and isinstance(v, dict):
                gi = v.get("GlobalElementIndex")
                ei = element_lookup.get(int(gi)) if gi and gi.isdigit() else {}
                sym = ei.get("ElementSymbol", "?")
                conc = v.get("StartConcentration", "?")
                pe = ei.get("PE_Spc_Number", "?")
                lines = []
                for sub in ei.values():
                    if isinstance(sub, dict) and "EmissionLines" in sub:
                        lines = sub["EmissionLines"]
                layer_info["Elements"].append({
                    "Symbol": sym,
                    "Conc": conc,
                    "PE_Spc_Number": pe,
                    "Lines": lines
                })

        layers.append(layer_info)

    data["Layers"] = layers
    return data


# ---------- STREAMLIT ----------
st.set_page_config(page_title="Bruker XMethod XADF Viewer", layout="wide")
st.title("🧪 Bruker XMethod XADF Summary Viewer")

uploaded=st.file_uploader("Upload a .xadf file",type=["xadf","XADF"])

if uploaded:
    try:
        tree=ET.parse(uploaded)
        root=tree.getroot()
        parsed=parse_xadf(root)
        info=parsed.get("Info",{}).get("Info",{})
        sample=info.get("APLName","Unknown Sample")
        st.header(f"📄 Sample: {sample}")

        # --- measurement conditions ---
        mp=parsed.get("MeasurementParameters",{})
        with st.expander("⚙️ Measurement Conditions", expanded=True):
            c1, c2 = st.columns(2)
            with c1:
                st.write(f"**Tube Element:** {mp.get('TubeElement', '?')} (Z={mp.get('TubeZ', '?')})")
                st.write(f"**Voltage (kV):** {mp.get('HV') or mp.get('TubeVoltage', '?')}")
                st.write(f"**Current (µA):** {mp.get('Current') or mp.get('TubeCurrent', '?')}")
                st.write(f"**Measurement Time (s):** {mp.get('Time', '?')}")
            with c2:
                st.write(f"**Number of Detectors:** {mp.get('NumberOfDetectors', '?')}")
                st.write(f"**Spot Size:** {mp.get('Collimator', {}).get('Description', '?')}")
                st.write(f"**Atmosphere:** {mp.get('AtmosphereName', '?')}")
                st.write(f"**Primary Spectrum (PrimarySpc):** {mp.get('PrimarySpc', '?')}")

        # --- layers ---
        st.subheader("🧱 Layer Structure")
        for L in parsed.get("Layers",[]):
            with st.expander(f"Layer {L['Index']}: {L.get('Description','')}",expanded=False):
                st.write(f"**Thickness:** {L.get('Thickness_um','?')} µm")
                st.write(f"**Density:** {L.get('Density_gcm3','?')} g/cm³")
                if L.get("Elements"):
                    df=pd.DataFrame([{
                        "Symbol":e.get("Symbol","?"),
                        "Conc":e.get("Conc","?"),
                        "PE_Spc_Number":e.get("PE_Spc_Number","?"),
                        "Emission Lines":", ".join(e.get("Lines",[]))
                    } for e in L["Elements"]])
                    st.dataframe(df,use_container_width=True)
                else:
                    st.info("No elements listed for this layer.")

        # --- visualization ---
        with st.expander("📊 Layer Composition (Stacked Bar)",expanded=True):
            rows=[]
            for L in parsed.get("Layers",[]):
                desc=L.get("Description",f"Layer {L['Index']}")
                for e in L.get("Elements",[]):
                    try: conc=float(e.get("Conc",0) or 0)
                    except: conc=0
                    rows.append({"Layer":desc,"Element":e.get("Symbol","?"),"Conc":conc})
            df=pd.DataFrame(rows)

            if df.empty:
                st.info("No element data available for visualization.")
            else:
                normalize = st.checkbox("Normalize layer concentrations (sum = 100 %)", value=False)
                if normalize:
                    df["Conc_norm"] = df.groupby("Layer")["Conc"].transform(
                        lambda x: x / x.sum() * 100 if x.sum()!=0 else x
                    )
                    yfield, ytitle = "Conc_norm", "Normalized Concentration (%)"
                else:
                    yfield, ytitle = "Conc", "Concentration (raw units)"

                fig = px.bar(df, x="Layer", y=yfield, color="Element",
                             barmode="stack", title="Layer Composition", text_auto=True)
                fig.update_yaxes(title=ytitle)
                st.plotly_chart(fig,use_container_width=True)

        # --- export buttons ---
        st.divider()
        full_json = json.dumps(parsed, indent=2, ensure_ascii=False)

        summary = {
            "SampleName": sample,
            "MeasurementConditions": mp,
            "Layers": parsed.get("Layers", []),
            "CalculationParameters": parsed.get("CalculationParameters", {})
        }
        summary_json = json.dumps(summary, indent=2, ensure_ascii=False)

        col1, col2 = st.columns(2)
        with col1:
            st.download_button(
                "💾 Save Full JSON (raw structure)",
                data=full_json,
                file_name=f"{sample}_full.json",
                mime="application/json"
            )
        with col2:
            st.download_button(
                "📘 Save Summary JSON",
                data=summary_json,
                file_name=f"{sample}_summary.json",
                mime="application/json"
            )

    except Exception as e:
        st.error(f"Error: {e}")

else:
    st.info("Upload a Bruker .xadf file to display the summary.")
