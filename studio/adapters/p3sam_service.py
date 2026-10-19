"""P3-RW multipart segmentation API. Proposals are never printable solids.

The recorded deployment uses POST /segment returning a ZIP, not an asynchronous
REST job. Submit once; an ambiguous POST cannot be resumed by submitting again.
Ordered triangle identity is checked before exporting source-bound face labels.
"""

from pathlib import Path
import hashlib
import json
import math
import time
import uuid
from urllib.parse import urlencode

import numpy as np
import trimesh

from studio.adapters.registry import BaseAdapter, register
from studio.adapters.transport import request, service_transport
from studio.core.editor import EditorError, _atomic

DEFAULTS = dict(
    seed=42, post_process=False, point_num=40000, prompt_num=400, prompt_bs=8,
    face_label_solver="random_walker", rw_sigma=1.0, rw_convex_scale=0.2,
    rw_cg_rtol=1e-5, rw_cg_maxiter=5000, rw_linear_solver="cudss",
    rw_cudss_device=0, rw_cudss_memory_limit_gb=20.0,
    relative_boundary_cost_threshold=0.5, post_process_area_coverage_threshold=0.95,
    mask_value_mode="binary", mask_clustering_method="nms", cluster_similarity_threshold=0.9,
    cluster_probability_aggregation="predicted_iou_argmax", mask_threshold=0.5,
    mask_branch_strategy="best_iou", mask_clustering_backend="cuda",
    mask_clustering_cuda_device=0, mask_clustering_cuda_batch_size=32,
    return_cos_url=False, return_glb=True,
)
# Confirmed against this deployment's live /openapi.json on 2026-10-10.
STRING_CHOICES = dict(
    mask_branch_strategy={"best_iou", "all"},
    mask_clustering_method={"nms", "complete_linkage"},
    cluster_probability_aggregation={"representative", "predicted_iou_weighted", "predicted_iou_argmax"},
)


def sha(path):
    with Path(path).open("rb") as stream:
        return hashlib.file_digest(stream, "sha256").hexdigest()


def ordered_binding(source, returned):
    x, y = source.triangles.reshape(-1, 3), returned.triangles.reshape(-1, 3)
    if x.shape != y.shape or not len(x) or not np.isfinite(x).all() or not np.isfinite(y).all():
        raise RuntimeError("分区返回的面序或几何不匹配 / Segmentation face order/geometry mismatch")
    ids = np.arange(0, len(x), max(1, len(x) // 20000))
    fit = np.linalg.lstsq(np.c_[x[ids], np.ones(len(ids))], y[ids], rcond=None)[0]
    singular = np.linalg.svd(fit[:3], compute_uv=False)
    error = np.linalg.norm(x @ fit[:3] + fit[3] - y, axis=1)
    tolerance = max(float(returned.extents.max()) * 2e-6, 1e-7)
    if singular.min() <= 0 or singular.max() / singular.min() > 1.00001 or np.linalg.det(fit[:3]) <= 0 or error.max() > tolerance:
        raise RuntimeError("无法绑定原始面；请重新映射 / Cannot bind original faces; explicit remapping required")
    return dict(transform=fit.tolist(), max_corner_error=float(error.max()), tolerance=tolerance,
                corners_checked=len(x), proper_similarity=True)


def source_scene(path):
    scene = trimesh.load(path, force="scene", process=False, allow_remote=False)
    nodes, meshes = {}, []
    for node in scene.graph.nodes_geometry:
        transform, geometry = scene.graph[node]
        mesh = scene.geometry[geometry].copy()
        if not isinstance(mesh, trimesh.Trimesh):
            raise RuntimeError("需要静态三角网格 / Static triangle meshes required")
        mesh.apply_transform(transform)
        nodes[str(node)] = len(mesh.faces)
        meshes.append(mesh)
    if not meshes:
        raise RuntimeError("模型无三角面 / Model has no triangles")
    return nodes, trimesh.util.concatenate(meshes)


def validate_result(source, folder, params):
    meta = json.loads((folder / "meta.json").read_text())
    echoed = [k for k in params if k not in ("return_cos_url", "return_glb", "prompt_bs")]
    if any(k not in meta or meta[k] != params[k] for k in echoed):
        raise RuntimeError("分区参数回显不匹配 / Segmentation parameter echo mismatch")
    nodes, original = source_scene(source)
    _, returned = source_scene(folder / "segment.glb")
    binding = ordered_binding(original, returned)
    labels = np.load(folder / "face_ids.npy", allow_pickle=False)
    if labels.shape != (len(original.faces),) or labels.dtype.kind not in "iu" or (labels < 0).any():
        raise RuntimeError("每一个原始面必须有有效分区标签 / Every original face requires a valid region label")
    offset, bound = 0, {}
    for node, count in nodes.items():
        bound[node] = [f"region-{int(i):03d}" for i in labels[offset:offset + count]]
        offset += count
    document = dict(source_sha256=sha(source), nodes=bound)
    (folder / "source-bound-labels.json").write_text(json.dumps(document, ensure_ascii=False))
    unique, counts = np.unique(labels, return_counts=True)
    report = dict(status="proposal", printable_solids=False, semantic_review_required=True,
                  source_sha256=sha(source), face_count=len(labels), region_count=len(unique),
                  regions=[dict(id=int(i), faces=int(n), area=float(original.area_faces[labels == i].sum()))
                           for i, n in zip(unique, counts)], ordered_binding=binding, parameter_echo=meta)
    (folder / "report.json").write_text(json.dumps(report, ensure_ascii=False, indent=2))
    return report


class P3Adapter(BaseAdapter):
    def operation_catalog(self, spec, item, *, internal_http):
        return dict(input_mode="files", timeout_seconds=600, operation_templates=[dict(
            id="segment", title="模型分区", params={k: DEFAULTS[k] for k in (
                "point_num", "prompt_num", "prompt_bs", "seed", "post_process", "face_label_solver", "mask_branch_strategy", "cluster_similarity_threshold")},
            labels=dict(point_num="采样点数", prompt_num="候选提示数", prompt_bs="提示批量", seed="随机种子",
                        post_process="后处理", face_label_solver="标签补全", mask_branch_strategy="分区候选保留方式",
                        cluster_similarity_threshold="候选合并相似度"),
            choices=dict(face_label_solver={"random_walker": "Random walker"},
                         mask_branch_strategy={"best_iou":"单一最优候选", "all":"保留多个候选"}),
            description="上传一个模型，返回分区预览和绑定原始面的标签。分区仍需封口、连接和制造检查。")],
            setup_message="配置自己的 HTTPS 或本机回环服务地址 / Configure your own HTTPS or loopback service endpoint.")

    def prepare_payload(self, spec, operation, payload):
        if operation != "segment" or set(payload) - set(DEFAULTS):
            raise EditorError("不支持的分区参数 / Unsupported segmentation parameters")
        params = {**DEFAULTS, **payload}
        for key in ("seed", "point_num", "prompt_num", "prompt_bs", "rw_cg_maxiter", "rw_cudss_device",
                    "mask_clustering_cuda_device", "mask_clustering_cuda_batch_size"):
            if type(params[key]) is not int or params[key] < 0:
                raise EditorError("分区整数参数无效 / Invalid segmentation integer parameter")
        if not 1000 <= params["point_num"] <= 100000 or not 1 <= params["prompt_num"] <= 1000 or not 1 <= params["prompt_bs"] <= 16:
            raise EditorError("分区采样或批量超出范围 / Segmentation sampling/batch out of range")
        for key, value in DEFAULTS.items():
            if isinstance(value, float) and (type(params[key]) not in (float, int) or not math.isfinite(params[key]) or params[key] <= 0):
                raise EditorError("分区数值必须为有限正数 / Segmentation values must be finite and positive")
            if isinstance(value, str) and params[key] not in STRING_CHOICES.get(key, {value}):
                raise EditorError("本连接仅支持已验证的 RW 参数 / This connector only supports verified RW choices")
        for key in ("cluster_similarity_threshold", "relative_boundary_cost_threshold", "post_process_area_coverage_threshold", "mask_threshold"):
            if params[key] > 1:
                raise EditorError("分区比例参数不能超过 1 / Segmentation probability exceeds 1")
        for key in ("post_process", "return_cos_url", "return_glb"):
            if type(params[key]) is not bool:
                raise EditorError("分区开关必须为布尔值 / Segmentation flags must be booleans")
        if params["return_cos_url"] or not params["return_glb"]:
            raise EditorError("需要直接返回 GLB ZIP / Direct GLB ZIP response required")
        return params

    def on_save(self, spec, template_spec, old):
        if spec.get("key_env") or spec.get("credential_ref"):
            raise EditorError("当前分区协议不需要密钥 / This segmentation protocol needs no key")
        service_transport(spec, submitting=True)

    def probe(self, spec):
        health = request(spec, "GET", "/health", timeout=15)
        if health.get("status") != "ok" or not health.get("model_loaded"):
            raise EditorError("分区模型尚未就绪 / Segmentation model is not ready")
        return dict(message="模型分区服务已就绪", model_loaded=True, inference_busy=health.get("inference_busy"),
                    solver=health.get("face_label_solver"), generation_started=False)

    def run(self, workbench):
        from studio.adapters.assembly_service import safe_extract

        data = workbench["params"]["service"]
        spec, params = data["spec"], self.prepare_payload(data["spec"], data["operation"], data["payload"])
        if len(workbench["inputs"]) != 1:
            raise RuntimeError("分区需要且仅需要一个模型 / Segmentation requires exactly one model")
        source = Path(workbench["inputs"][0])
        if source.suffix.lower() not in (".glb", ".stl", ".obj", ".ply") or source.stat().st_size > 100 * 1024 * 1024:
            raise RuntimeError("不支持的分区输入 / Unsupported segmentation input")
        output = Path(workbench["output"])
        receipt, response = output.parent / "service-receipt.json", output.parent / "p3-response.zip"
        ledger = json.loads(receipt.read_text()) if receipt.exists() else {}
        source_hash = sha(source)

        def save(**updates):
            ledger.update(updates)
            _atomic(receipt, json.dumps(ledger).encode())

        if ledger and (ledger.get("source_sha256") != source_hash or ledger.get("request_params") != params):
            raise RuntimeError("恢复请求与原始分区不一致 / Resume differs from original segmentation")
        if not response.exists():
            if ledger.get("submission_attempted"):
                raise RuntimeError("分区提交状态不明确；不会自动重复提交 / Ambiguous submission; no automatic resubmit")
            self.probe(spec)
            boundary = "Workbench" + uuid.uuid4().hex
            content = source.read_bytes()
            raw = (f'--{boundary}\r\nContent-Disposition: form-data; name="file"; filename="source{source.suffix.lower()}"\r\n'
                   'Content-Type: application/octet-stream\r\n\r\n').encode() + content + f"\r\n--{boundary}--\r\n".encode()
            save(provider=data["provider"], adapter="p3sam", operation="segment", submission_attempted=True,
                 source_sha256=source_hash, request_params=params, submitted_at=time.time(), status="submitting")
            query = urlencode({k: str(v).lower() if isinstance(v, bool) else v for k, v in params.items()})
            result = request(spec, "POST", "/segment?" + query, raw=raw,
                             content_type="multipart/form-data; boundary=" + boundary, timeout=540, binary=True)
            _atomic(response, result)
            save(response_sha256=sha(response), status="received", received_at=time.time())
        if sha(response) != ledger.get("response_sha256"):
            raise RuntimeError("分区回执指纹不一致 / Segmentation response hash mismatch")
        safe_extract(response, output / "segmentation")
        folder = output / "segmentation"
        report = validate_result(source, folder, params)
        # Native material preview is kept separately from the returned colored proposal.
        (output / "service.json").write_text(json.dumps(dict(
            provider=data["provider"], adapter="p3sam", operation="segment", status="succeeded",
            input_sha256=[dict(path=str(source), sha256=source_hash)], request_params=params,
            submitted_at=ledger["submitted_at"], received_at=ledger["received_at"],
            cost=None, cost_unit=None, cost_note="费用未返回", region_count=report["region_count"],
            printable_solids=False, semantic_review_required=True), ensure_ascii=False, indent=2))
        save(status="succeeded")


register("p3sam")(P3Adapter())
