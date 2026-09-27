import JSZip from "jszip";

import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";
import type { QuestionSnapshot, BatchSnapshot, CapturedImageSources } from "./exportSnapshot";

export function formatTimestamp(): string {
  const now = new Date();
  const pad = (n: number) => String(n).padStart(2, "0");
  return (
    `${now.getFullYear()}-${pad(now.getMonth() + 1)}-${pad(now.getDate())}` +
    `T${pad(now.getHours())}-${pad(now.getMinutes())}-${pad(now.getSeconds())}`
  );
}

function xmlEscape(str: string): string {
  return str
    .replace(/&/g, "&amp;")
    .replace(/</g, "&lt;")
    .replace(/>/g, "&gt;")
    .replace(/"/g, "&quot;")
    .replace(/'/g, "&apos;");
}

function base64ToUint8Array(b64: string): Uint8Array {
  const binary = atob(b64);
  const arr = new Uint8Array(binary.length);
  for (let i = 0; i < binary.length; i++) arr[i] = binary.charCodeAt(i);
  return arr;
}

function buildMeta(title: string, isoDate: string): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<office:document-meta
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:dc="http://purl.org/dc/elements/1.1/"
  office:version="1.3">
  <office:meta>
    <dc:title>${xmlEscape(title)}</dc:title>
    <dc:date>${xmlEscape(isoDate)}</dc:date>
  </office:meta>
</office:document-meta>`;
}

function buildStyles(): string {
  return `<?xml version="1.0" encoding="UTF-8"?>
<office:document-styles
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:style="urn:oasis:names:tc:opendocument:xmlns:style:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:fo="urn:oasis:names:tc:opendocument:xmlns:xsl-fo-compatible:1.0"
  office:version="1.3">
  <office:styles>
    <style:style style:name="Standard" style:family="paragraph" style:class="text">
      <style:paragraph-properties fo:margin-bottom="0.2cm"/>
      <style:text-properties fo:font-size="11pt"/>
    </style:style>
    <style:style style:name="Heading1" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-top="0.5cm" fo:margin-bottom="0.2cm"/>
      <style:text-properties fo:font-size="14pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="Heading2" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:margin-top="0.3cm" fo:margin-bottom="0.1cm"/>
      <style:text-properties fo:font-size="11pt" fo:font-weight="bold"/>
    </style:style>
    <style:style style:name="MetaLine" style:family="paragraph" style:parent-style-name="Standard">
      <style:text-properties fo:font-size="9pt" fo:color="#666666"/>
    </style:style>
    <style:style style:name="PageBreak" style:family="paragraph" style:parent-style-name="Standard">
      <style:paragraph-properties fo:break-before="page" fo:margin-bottom="0cm"/>
    </style:style>
  </office:styles>
</office:document-styles>`;
}

interface Section {
  question: ExamQuestion;
  imageRef?: string;
  subImageRefs?: Record<string, string>;
}

function subImageKey(id: string | undefined, sequence: number): string {
  return id && id.length > 0 ? id : String(sequence);
}

function buildImageParagraph(name: string, imageRef: string, zIndex: number): string {
  return (
    `<text:p text:style-name="Standard">` +
      `<draw:frame draw:name="${xmlEscape(name)}" text:anchor-type="as-char" ` +
      `svg:width="12cm" svg:height="9cm" draw:z-index="${zIndex}">` +
      `<draw:image xlink:href="${xmlEscape(imageRef)}" xlink:type="simple" ` +
      `xlink:show="embed" xlink:actuate="onLoad"/>` +
      `</draw:frame>` +
      `</text:p>`
  );
}

function buildMetadataItems(question: ExamQuestion): string[] {
  const isSocialStudies = (question.subquestions?.length ?? 0) > 0;
  const isIccsEra = question.認知歷程 !== undefined && question.認知歷程 !== null;
  const eraMetadata = isIccsEra
    ? [question.內容領域, ...(question.認知歷程 ?? [])]
    : [...(question.閱讀歷程 ?? []), question.文本形式];
  if (isSocialStudies) {
    const subs = question.subquestions!;
    const unique = <T>(arr: T[]): T[] => [...new Set(arr)];
    return [
      ...unique(subs.map((s) => `${s.年級}年級`)),
      ...unique(subs.flatMap((s) => s.科目)),
      ...unique(subs.flatMap((s) => s.核心素養)),
      ...unique(subs.flatMap((s) => s.學習內容.map((lc) => lc.編碼))),
      ...unique(subs.flatMap((s) => s.學習表現.map((lp) => lp.編碼))),
      ...eraMetadata,
    ].filter((item): item is string => Boolean(item));
  }
  return [
    ...(question.情境 ?? []),
    question.題型種類,
    question.題型,
    ...(question.數學思考 ?? []),
    ...(question.學習內容 ?? []).map((c) => c.編碼).filter(Boolean),
    ...eraMetadata,
  ].filter((item): item is string => Boolean(item));
}

function isInteractiveSubQuestion(sub: SubQuestion): boolean {
  return sub.題型 === "拖放題" || sub.題型 === "滑桿題" || Boolean(sub.interaction);
}

function buildContentXml(title: string, sections: Section[], isMultiple: boolean): string {
  const paras: string[] = [];

  if (isMultiple && title) {
    paras.push(`<text:p text:style-name="Heading1">${xmlEscape(title)}</text:p>`);
  }

  sections.forEach(({ question, imageRef, subImageRefs }, idx) => {
    try {
    if (isMultiple) {
      if (idx > 0) {
        paras.push(`<text:p text:style-name="PageBreak"/>`);
      }
      paras.push(`<text:p text:style-name="Heading1">${xmlEscape(`Question ${idx + 1}`)}</text:p>`);
    }

    // Metadata chips line
    const meta = buildMetadataItems(question)
      .map(xmlEscape)
      .join(" ｜ ");
    if (meta) {
      paras.push(`<text:p text:style-name="MetaLine">${meta}</text:p>`);
    }

    // Embedded image
    if (imageRef) {
      paras.push(buildImageParagraph(`img${idx}`, imageRef, idx));
    }

    const isSocialStudies = (question.subquestions?.length ?? 0) > 0;

    if (isSocialStudies) {
      // Core question
      if (question.核心問題) {
        paras.push(`<text:p text:style-name="Heading2">${xmlEscape("核心問題")}</text:p>`);
        paras.push(`<text:p text:style-name="Standard">${xmlEscape(question.核心問題)}</text:p>`);
      }
      // Passage
      if (question.文本) {
        paras.push(`<text:p text:style-name="Heading2">${xmlEscape("文本")}</text:p>`);
        paras.push(`<text:p text:style-name="Standard">${xmlEscape(question.文本)}</text:p>`);
      }
      // Subquestions
      const omittedInteractiveSubquestions = question.subquestions!.filter(isInteractiveSubQuestion);
      question.subquestions!.forEach((sub) => {
        if (isInteractiveSubQuestion(sub)) return;

        const subMeta = [
          `${sub.年級}年級`,
          sub.題型,
          ...(sub.科目 ?? []),
          ...(sub.核心素養 ?? []),
          ...(sub.學習內容 ?? []).map((lc) => lc.編碼),
          ...(sub.學習表現 ?? []).map((lp) => lp.編碼),
          sub.認知歷程,
        ].filter((item): item is string => Boolean(item)).map(xmlEscape).join(" ｜ ");
        paras.push(`<text:p text:style-name="Heading2">${xmlEscape(`第${sub.序號}題`)}</text:p>`);
        if (subMeta) {
          paras.push(`<text:p text:style-name="MetaLine">${subMeta}</text:p>`);
        }
        const subImageRef = sectionSubImageRef(sub.序號, sub.id, subImageRefs);
        if (subImageRef) {
          paras.push(buildImageParagraph(`img${idx}_sq${sub.序號}`, subImageRef, idx));
        }
        paras.push(`<text:p text:style-name="Standard">${xmlEscape(sub.題目)}</text:p>`);
        paras.push(`<text:p text:style-name="MetaLine">${xmlEscape("答案：")}${xmlEscape(sub.答案)}</text:p>`);
        if (sub.答案解析) {
          paras.push(`<text:p text:style-name="MetaLine">${xmlEscape("解析：")}${xmlEscape(sub.答案解析)}</text:p>`);
        }
        if (sub.評分規準?.length) {
          paras.push(`<text:p text:style-name="MetaLine">${xmlEscape("評分規準：")}</text:p>`);
          sub.評分規準.forEach((r) => {
            paras.push(`<text:p text:style-name="Standard">${xmlEscape(`[${r.code}] ${r.規準說明}`)}</text:p>`);
          });
        }
        if (sub.誘答分析 && Object.keys(sub.誘答分析).length > 0) {
          paras.push(`<text:p text:style-name="MetaLine">${xmlEscape("誘答分析：")}</text:p>`);
          Object.entries(sub.誘答分析).forEach(([label, note]) => {
            paras.push(
              `<text:p text:style-name="Standard">${xmlEscape(`[${label}] ${note}`)}</text:p>`,
            );
          });
        }
      });
      if (omittedInteractiveSubquestions.length > 0) {
        const omittedItems = omittedInteractiveSubquestions
          .map((sub) => `第${sub.序號}小題（${sub.題型}）`)
          .join("、");
        paras.push(
          `<text:p text:style-name="MetaLine">${xmlEscape(
            `以下互動題目未列入紙本輸出，請於網頁檢視器作答：${omittedItems}`,
          )}</text:p>`,
        );
      }
    } else {
      // Math: flat question + solution
      paras.push(`<text:p text:style-name="Heading2">${xmlEscape("題目")}</text:p>`);
      question.題目.forEach((line) => {
        paras.push(`<text:p text:style-name="Standard">${xmlEscape(line)}</text:p>`);
      });
      paras.push(`<text:p text:style-name="Heading2">${xmlEscape("正確解題分析")}</text:p>`);
      question.正確解題分析.forEach((line) => {
        paras.push(`<text:p text:style-name="Standard">${xmlEscape(line)}</text:p>`);
      });
      if (question.誘答分析 && Object.keys(question.誘答分析).length > 0) {
        paras.push(`<text:p text:style-name="Heading2">${xmlEscape("誘答分析")}</text:p>`);
        Object.entries(question.誘答分析).forEach(([label, note]) => {
          paras.push(
            `<text:p text:style-name="Standard">${xmlEscape(`[${label}] ${note}`)}</text:p>`,
          );
        });
      }
    }
    } catch (error: unknown) {
      throw new OdtBuildError(idx, error);
    }
  });

  return `<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
  office:version="1.3">
  <office:body>
    <office:text>
      ${paras.join("\n      ")}
    </office:text>
  </office:body>
</office:document-content>`;
}

function sectionSubImageRef(
  sequence: number,
  id: string | undefined,
  subImageRefs: Record<string, string> | undefined,
): string | undefined {
  if (!subImageRefs) return undefined;
  return subImageRefs[subImageKey(id, sequence)] ?? subImageRefs[String(sequence)];
}

function buildManifest(imageRefs: string[]): string {
  const imgEntries = imageRefs
    .map(
      (ref) =>
        `  <manifest:file-entry manifest:full-path="${xmlEscape(ref)}" manifest:media-type="image/png"/>`
    )
    .join("\n");
  return `<?xml version="1.0" encoding="UTF-8"?>
<manifest:manifest
  xmlns:manifest="urn:oasis:names:tc:opendocument:xmlns:manifest:1.0"
  manifest:version="1.3">
  <manifest:file-entry manifest:full-path="/" manifest:media-type="application/vnd.oasis.opendocument.text"/>
  <manifest:file-entry manifest:full-path="content.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="styles.xml" manifest:media-type="text/xml"/>
  <manifest:file-entry manifest:full-path="meta.xml" manifest:media-type="text/xml"/>
${imgEntries}
</manifest:manifest>`;
}

export class OdtBuildError extends Error {
  readonly questionIndex: number;

  constructor(questionIndex: number, cause: unknown) {
    super(cause instanceof Error ? cause.message : "ODT question build failed");
    this.name = "OdtBuildError";
    this.questionIndex = questionIndex;
  }
}

export async function buildExamOdt(title: string, questions: ExamQuestion[]): Promise<Blob> {
  const zip = new JSZip();
  const isMultiple = questions.length > 1;
  const isoDate = new Date().toISOString();

  // Must be STORE (no compression) — ODT spec requirement
  zip.file("mimetype", "application/vnd.oasis.opendocument.text", { compression: "STORE" });

  const imageRefs: string[] = [];
  const sections: Section[] = questions.map((q, idx) => {
    try {
      const section: Section = { question: q };
      if (q.image_base64) {
        const ref = `Pictures/img_${idx}.png`;
        imageRefs.push(ref);
        section.imageRef = ref;
        zip.file(ref, base64ToUint8Array(q.image_base64));
      }
      q.subquestions?.forEach((sub) => {
        if (!sub.image_base64) return;
        const ref = `Pictures/img_${idx}_sq_${sub.序號}.png`;
        imageRefs.push(ref);
        section.subImageRefs = {
          ...(section.subImageRefs ?? {}),
          [subImageKey(sub.id, sub.序號)]: ref,
          [String(sub.序號)]: ref,
        };
        zip.file(ref, base64ToUint8Array(sub.image_base64));
      });
      return section;
    } catch (error: unknown) {
      throw new OdtBuildError(idx, error);
    }
  });

  zip.file("meta.xml", buildMeta(title, isoDate));
  zip.file("styles.xml", buildStyles());
  zip.file("content.xml", buildContentXml(title, sections, isMultiple));
  zip.file("META-INF/manifest.xml", buildManifest(imageRefs));

  return zip.generateAsync({
    type: "blob",
    mimeType: "application/vnd.oasis.opendocument.text",
  });
}

// ---------------------------------------------------------------------------
// Snapshot-aware ODT builder (issue #752)
// ---------------------------------------------------------------------------
//
// Consumes a frozen QuestionSnapshot produced by exportSnapshot.ts.
// Uses `imageSources` for all image embedding, NOT `question.image_base64`,
// so images are bound to the snapshot revision and a later arrival never
// silently substitutes a different version.
//
// chart_spec_preview conversion is NOT yet implemented (blocked on issue #753).
// Until #753 ships, a chart_spec_preview slot emits a visible placeholder paragraph
// ("圖片預覽待轉換，請至網頁版查看") at the correct position; the ODT is still
// downloadable and all other content is unaffected.
//
// TODO(#753): replace the chart_spec_preview placeholder with actual rasterisation.

interface SnapshotSection {
  snapshot: QuestionSnapshot;
  imageRef?: string;
  subImageRefs?: Record<string, string>; // key: String(序號)
}

function buildStatusLabel(snapshot: QuestionSnapshot): string | null {
  const meta = snapshot.exported._export;
  const parts: string[] = [];

  // Processing
  const processingMap: Record<string, string> = {
    waiting: "等候生成",
    running: "生成中",
    ended: "已結束",
    unknown: "處理狀態未知",
  };
  parts.push(`處理：${processingMap[meta.processing] ?? meta.processing}`);

  // Delivery
  if (meta.delivery_status) {
    const deliveryMap: Record<string, string> = {
      complete: "完整",
      partial: "部分",
      none: "無結果",
      unknown: "未知",
    };
    parts.push(`交付：${deliveryMap[meta.delivery_status] ?? meta.delivery_status}`);
  } else {
    // No terminal received — delivery status unknown
    parts.push("交付：未知（未收到 terminal）");
  }

  // Review
  const reviewMap: Record<string, string> = {
    passed: "通過",
    failed: "未通過",
    skipped: "略過",
    unknown: "未知",
  };
  parts.push(`審題：${reviewMap[meta.review.status] ?? meta.review.status}`);

  return parts.join("　");
}

/**
 * Gather image refs from the frozen `imageSources` and add them to the ZIP.
 * Returns the stem image ref and a per-subquestion ref map.
 *
 * chart_spec_preview: emits a placeholder marker (TODO #753).
 * known_missing: marked in the content XML via the missing-marker helper; no file embedded.
 */
function embedSnapshotImages(
  zip: JSZip,
  snapshot: QuestionSnapshot,
  idx: number,
  imageRefs: string[],
): { stemImageRef?: string; subImageRefs: Record<string, string>; stemIsPreview: boolean; subPreviewKeys: Set<string> } {
  const sources: CapturedImageSources = snapshot.imageSources;
  let stemImageRef: string | undefined;
  let stemIsPreview = false;
  const subImageRefs: Record<string, string> = {};
  const subPreviewKeys = new Set<string>();

  const stemSource = sources["stem"];
  if (stemSource) {
    if (stemSource.kind === "png_base64" && stemSource.pngBase64) {
      const ref = `Pictures/img_snap_${idx}.png`;
      imageRefs.push(ref);
      stemImageRef = ref;
      zip.file(ref, base64ToUint8Array(stemSource.pngBase64));
    } else if (stemSource.kind === "chart_spec_preview") {
      // TODO(#753): rasterize chart_spec_preview
      stemIsPreview = true;
    }
    // kind === "known_missing": no file; marked in XML
  }

  // Per-subquestion images
  for (const [key, source] of Object.entries(sources)) {
    if (key === "stem") continue;
    // key is "sq{序號}" — extract 序號
    const seqMatch = /^sq(\d+)$/.exec(key);
    if (!seqMatch) continue;
    const seq = seqMatch[1];

    if (source.kind === "png_base64" && source.pngBase64) {
      const ref = `Pictures/img_snap_${idx}_sq_${seq}.png`;
      imageRefs.push(ref);
      subImageRefs[seq] = ref;
      zip.file(ref, base64ToUint8Array(source.pngBase64));
    } else if (source.kind === "chart_spec_preview") {
      // TODO(#753): rasterize chart_spec_preview
      subPreviewKeys.add(seq);
    }
    // kind === "known_missing": no file; marked in XML
  }

  return { stemImageRef, subImageRefs, stemIsPreview, subPreviewKeys };
}

/**
 * Build content XML for snapshot-based exports. Preserves:
 * - Draft label
 * - Processing/delivery/review status (separately stated)
 * - Original subquestion 序號 with gaps
 * - Known-missing subquestion and image markers at correct positions
 * - Final without terminal = final + unknown processing
 */
function buildSnapshotContentXml(title: string, sections: SnapshotSection[], isMultiple: boolean): string {
  const paras: string[] = [];

  if (isMultiple && title) {
    paras.push(`<text:p text:style-name="Heading1">${xmlEscape(title)}</text:p>`);
  }

  sections.forEach(({ snapshot, imageRef: stemImageRef, subImageRefs }, idx) => {
    try {
      const { exported: question } = snapshot;
      const meta = question._export;

      if (isMultiple) {
        if (idx > 0) {
          paras.push(`<text:p text:style-name="PageBreak"/>`);
        }
        paras.push(`<text:p text:style-name="Heading1">${xmlEscape(`Question ${idx + 1}`)}</text:p>`);
      }

      // --- Draft label ---
      if (meta.is_draft) {
        paras.push(`<text:p text:style-name="MetaLine">${xmlEscape("【草稿】此題尚未完成最終審核")}</text:p>`);
      }

      // --- Status line ---
      const statusLabel = buildStatusLabel(snapshot);
      if (statusLabel) {
        paras.push(`<text:p text:style-name="MetaLine">${xmlEscape(statusLabel)}</text:p>`);
      }

      // --- Metadata chips (same as existing buildMetadataItems) ---
      const meta_chips = buildMetadataItems(question as ExamQuestion)
        .map(xmlEscape)
        .join(" ｜ ");
      if (meta_chips) {
        paras.push(`<text:p text:style-name="MetaLine">${meta_chips}</text:p>`);
      }

      // --- Stem image (from imageSources, not question.image_base64) ---
      if (stemImageRef) {
        paras.push(buildImageParagraph(`snap_img${idx}`, stemImageRef, idx));
      } else {
        // Check if stem has chart_spec_preview or known_missing
        const stemSrc = snapshot.imageSources["stem"];
        if (stemSrc?.kind === "chart_spec_preview") {
          // TODO(#753): rasterize; for now emit placeholder
          paras.push(
            `<text:p text:style-name="MetaLine">${xmlEscape("【圖片預覽待轉換，請至網頁版查看】")}</text:p>`
          );
        } else if (stemSrc?.kind === "known_missing") {
          paras.push(
            `<text:p text:style-name="MetaLine">${xmlEscape("【缺圖：此位置應有圖片，但尚未生成或已遺失】")}</text:p>`
          );
        }
      }

      const isSocialStudies = (question.subquestions?.length ?? 0) > 0
        || meta.missing.some((s) => s.kind === "subquestion");

      if (isSocialStudies) {
        // Core question
        if ((question as ExamQuestion).核心問題) {
          paras.push(`<text:p text:style-name="Heading2">${xmlEscape("核心問題")}</text:p>`);
          paras.push(`<text:p text:style-name="Standard">${xmlEscape((question as ExamQuestion).核心問題!)}</text:p>`);
        }
        // Passage
        if ((question as ExamQuestion).文本) {
          paras.push(`<text:p text:style-name="Heading2">${xmlEscape("文本")}</text:p>`);
          paras.push(`<text:p text:style-name="Standard">${xmlEscape((question as ExamQuestion).文本!)}</text:p>`);
        }

        // Build a sorted list of all known 序號 slots (received + missing-subquestion)
        const receivedSubqs = (question.subquestions ?? []).filter(
          (sub) => !isInteractiveSubQuestion(sub as SubQuestion)
        );
        const missingSubqIndices = new Set<number>(
          meta.missing
            .filter((s) => s.kind === "subquestion" && typeof s.subquestion_index === "number")
            .map((s) => s.subquestion_index as number)
        );
        // All 序號 values (received + missing), sorted
        const receivedIndices = new Set(receivedSubqs.map((s) => s.序號));
        const allIndices = [...new Set([...receivedIndices, ...missingSubqIndices])].sort(
          (a, b) => a - b
        );
        const subqByIndex = new Map(receivedSubqs.map((s) => [s.序號, s as SubQuestion]));

        const omittedInteractive = (question.subquestions ?? []).filter(
          (sub) => isInteractiveSubQuestion(sub as SubQuestion)
        );

        for (const seqNo of allIndices) {
          const sub = subqByIndex.get(seqNo);
          if (!sub) {
            // Known-missing subquestion
            paras.push(
              `<text:p text:style-name="Heading2">${xmlEscape(`第${seqNo}題`)}</text:p>`
            );
            paras.push(
              `<text:p text:style-name="MetaLine">${xmlEscape(`【缺小題 ${seqNo}：此小題已知缺失】`)}</text:p>`
            );
            continue;
          }

          // Received subquestion
          const subMeta = [
            `${sub.年級}年級`,
            sub.題型,
            ...(sub.科目 ?? []),
            ...(sub.核心素養 ?? []),
            ...(sub.學習內容 ?? []).map((lc: { 編碼: string }) => lc.編碼),
            ...(sub.學習表現 ?? []).map((lp: { 編碼: string }) => lp.編碼),
            (sub as SubQuestion & { 認知歷程?: string }).認知歷程,
          ].filter((item): item is string => Boolean(item)).map(xmlEscape).join(" ｜ ");

          paras.push(`<text:p text:style-name="Heading2">${xmlEscape(`第${seqNo}題`)}</text:p>`);
          if (subMeta) {
            paras.push(`<text:p text:style-name="MetaLine">${subMeta}</text:p>`);
          }

          // Subquestion image from imageSources
          const sqKey = String(seqNo);
          const sqImageRef = subImageRefs?.[sqKey];
          if (sqImageRef) {
            paras.push(buildImageParagraph(`snap_img${idx}_sq${seqNo}`, sqImageRef, idx));
          } else {
            const sqSrc = snapshot.imageSources[`sq${seqNo}`];
            if (sqSrc?.kind === "chart_spec_preview") {
              // TODO(#753): rasterize; for now emit placeholder
              paras.push(
                `<text:p text:style-name="MetaLine">${xmlEscape("【圖片預覽待轉換，請至網頁版查看】")}</text:p>`
              );
            } else if (sqSrc?.kind === "known_missing") {
              paras.push(
                `<text:p text:style-name="MetaLine">${xmlEscape(`【缺圖：第${seqNo}題圖片已知缺失】`)}</text:p>`
              );
            }
          }

          paras.push(`<text:p text:style-name="Standard">${xmlEscape(sub.題目)}</text:p>`);
          paras.push(
            `<text:p text:style-name="MetaLine">${xmlEscape("答案：")}${xmlEscape(sub.答案)}</text:p>`
          );
          if (sub.答案解析) {
            paras.push(
              `<text:p text:style-name="MetaLine">${xmlEscape("解析：")}${xmlEscape(sub.答案解析)}</text:p>`
            );
          }
          if (sub.評分規準?.length) {
            paras.push(`<text:p text:style-name="MetaLine">${xmlEscape("評分規準：")}</text:p>`);
            sub.評分規準.forEach((r: { code: string; 規準說明: string }) => {
              paras.push(
                `<text:p text:style-name="Standard">${xmlEscape(`[${r.code}] ${r.規準說明}`)}</text:p>`
              );
            });
          }
          if (sub.誘答分析 && Object.keys(sub.誘答分析).length > 0) {
            paras.push(`<text:p text:style-name="MetaLine">${xmlEscape("誘答分析：")}</text:p>`);
            Object.entries(sub.誘答分析).forEach(([label, note]) => {
              paras.push(
                `<text:p text:style-name="Standard">${xmlEscape(`[${label}] ${note}`)}</text:p>`
              );
            });
          }
        }

        // Omitted interactive subquestions manifest
        if (omittedInteractive.length > 0) {
          const omittedItems = omittedInteractive
            .map((sub) => `第${sub.序號}小題（${sub.題型}）`)
            .join("、");
          paras.push(
            `<text:p text:style-name="MetaLine">${xmlEscape(
              `以下互動題目未列入紙本輸出，請於網頁檢視器作答：${omittedItems}`
            )}</text:p>`
          );
        }

        // Known-missing image slots for subquestions not covered by subquestion rendering
        // (e.g. standalone image slots where subquestion itself was delivered but image is missing
        // — those are handled per-subquestion above via imageSources["sq{N}"])
        // Stem-level missing image is handled above; nothing more needed here.

      } else {
        // Math flat question
        paras.push(`<text:p text:style-name="Heading2">${xmlEscape("題目")}</text:p>`);
        question.題目.forEach((line) => {
          paras.push(`<text:p text:style-name="Standard">${xmlEscape(line)}</text:p>`);
        });
        paras.push(`<text:p text:style-name="Heading2">${xmlEscape("正確解題分析")}</text:p>`);
        question.正確解題分析.forEach((line) => {
          paras.push(`<text:p text:style-name="Standard">${xmlEscape(line)}</text:p>`);
        });
        if ((question as ExamQuestion).誘答分析 && Object.keys((question as ExamQuestion).誘答分析!).length > 0) {
          paras.push(`<text:p text:style-name="Heading2">${xmlEscape("誘答分析")}</text:p>`);
          Object.entries((question as ExamQuestion).誘答分析!).forEach(([label, note]) => {
            paras.push(
              `<text:p text:style-name="Standard">${xmlEscape(`[${label}] ${note}`)}</text:p>`
            );
          });
        }
      }

      // --- Known-missing items summary (at the end of each question) ---
      const missingImageSlots = meta.missing.filter((s) => s.kind === "image");
      const missingSubqSlots = meta.missing.filter((s) => s.kind === "subquestion");
      const hasMissingInfo = missingImageSlots.length > 0 || missingSubqSlots.length > 0;
      if (hasMissingInfo && !isSocialStudies) {
        // For flat questions, list known-missing at the end (images handled per-slot above)
        if (missingImageSlots.length > 0) {
          paras.push(
            `<text:p text:style-name="MetaLine">${xmlEscape("【已知缺圖：此題應有圖片，但尚未生成或已遺失】")}</text:p>`
          );
        }
      }

    } catch (error: unknown) {
      throw new OdtBuildError(idx, error);
    }
  });

  return `<?xml version="1.0" encoding="UTF-8"?>
<office:document-content
  xmlns:office="urn:oasis:names:tc:opendocument:xmlns:office:1.0"
  xmlns:text="urn:oasis:names:tc:opendocument:xmlns:text:1.0"
  xmlns:draw="urn:oasis:names:tc:opendocument:xmlns:drawing:1.0"
  xmlns:xlink="http://www.w3.org/1999/xlink"
  xmlns:svg="urn:oasis:names:tc:opendocument:xmlns:svg-compatible:1.0"
  office:version="1.3">
  <office:body>
    <office:text>
      ${paras.join("\n      ")}
    </office:text>
  </office:body>
</office:document-content>`;
}

/**
 * Build an ODT from a list of QuestionSnapshots.
 *
 * This is the snapshot-aware counterpart to `buildExamOdt`. Unlike that function,
 * this one uses the frozen `imageSources` for all image embedding (not `question.image_base64`),
 * adds draft labels, status lines, and missing-item markers.
 *
 * chart_spec_preview conversion is not yet implemented (blocked on issue #753).
 * Until then, a text placeholder is emitted at the preview position.
 */
export async function buildOdtFromSnapshots(
  title: string,
  snapshots: QuestionSnapshot[],
): Promise<Blob> {
  const zip = new JSZip();
  const isMultiple = snapshots.length > 1;
  const isoDate = new Date().toISOString();

  zip.file("mimetype", "application/vnd.oasis.opendocument.text", { compression: "STORE" });

  const imageRefs: string[] = [];
  const sections: SnapshotSection[] = snapshots.map((snapshot, idx) => {
    try {
      const { stemImageRef, subImageRefs } = embedSnapshotImages(
        zip, snapshot, idx, imageRefs,
      );
      const section: SnapshotSection = { snapshot };
      if (stemImageRef) section.imageRef = stemImageRef;
      if (Object.keys(subImageRefs).length > 0) section.subImageRefs = subImageRefs;
      return section;
    } catch (error: unknown) {
      throw new OdtBuildError(idx, error);
    }
  });

  zip.file("meta.xml", buildMeta(title, isoDate));
  zip.file("styles.xml", buildStyles());
  zip.file("content.xml", buildSnapshotContentXml(title, sections, isMultiple));
  zip.file("META-INF/manifest.xml", buildManifest(imageRefs));

  return zip.generateAsync({
    type: "blob",
    mimeType: "application/vnd.oasis.opendocument.text",
  });
}

/**
 * Build an ODT from a BatchSnapshot.
 * Wraps `buildOdtFromSnapshots` with batch-level title/filename logic.
 */
export async function buildOdtFromBatch(
  title: string,
  batch: BatchSnapshot,
): Promise<Blob> {
  // BatchSnapshot.exported is ExportedQuestion[]; we need QuestionSnapshot[]
  // but BatchSnapshot does not store imageSources. This overload is for callers
  // that want to drive from a BatchSnapshot; they should use buildOdtFromSnapshots
  // directly when QuestionSnapshot[] is available (which is the preferred path).
  // This overload builds minimal snapshots with empty imageSources.
  const snapshots: QuestionSnapshot[] = batch.exported.map((eq) => {
    // eslint-disable-next-line @typescript-eslint/no-unused-vars
    const { _export: _removed, ...rest } = eq;
    return {
      exported: eq,
      captured: rest as ExamQuestion,
      isDraft: eq._export.is_draft,
      index: eq._export.index,
      imageSources: {},
    };
  });
  return buildOdtFromSnapshots(title, snapshots);
}
