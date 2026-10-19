"""Shared laser tool schema."""
TOOLS=[{
    "name":"studio_laser",
    "description":"R1 board-based laser workflow. create a parametric open-bottom tissue box (inner dimensions in mm), then run design, panels, nest, lightburn in order. Read current revision before each run. Outputs include real assembly GLB, finger-jointed closed SVG panels, kerf-compensated sheets within R1 600x300 mm, and real LightBurn REST import receipts. connect requires consent in LightBurn 2.2+. lightburn requires an empty LightBurn project; select sheet for multiple sheets. Import never fires a laser or validates material settings. Parameters are immutable; create a new workflow to change them. artifact returns verified base64 file content for UI preview/download.",
    "inputSchema":{"type":"object","properties":{
        "action":{"type":"string","enum":["list","create","read","run","artifact","connect","connection"]},
        "id":{"type":"string"},"expected_revision":{"type":"integer"},"title":{"type":"string"},
        "stage":{"type":"string","enum":["design","panels","nest","lightburn"]},
        "sheet":{"type":"integer","minimum":1},"name":{"type":"string"},
        "params":{"type":"object","properties":{k:{"type":"number"} for k in ["width_mm","depth_mm","height_mm","thickness_mm","slot_length_mm","slot_width_mm","clearance_mm","kerf_mm","sheet_width_mm","sheet_height_mm","margin_mm","gap_mm"]},"additionalProperties":False}
    },"required":["action"],"additionalProperties":False},
    "readOnly":False,"method":"POST","path":"/api/laser"
}]
