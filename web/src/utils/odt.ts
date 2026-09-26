import JSZip from "jszip";

import type { ExamQuestion, SubQuestion } from "../hooks/useGenerate";

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

export async function buildExamOdt(title: string, questions: ExamQuestion[]): Promise<Blob> {
  const zip = new JSZip();
  const isMultiple = questions.length > 1;
  const isoDate = new Date().toISOString();

  // Must be STORE (no compression) — ODT spec requirement
  zip.file("mimetype", "application/vnd.oasis.opendocument.text", { compression: "STORE" });

  const imageRefs: string[] = [];
  const sections: Section[] = questions.map((q, idx) => {
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
