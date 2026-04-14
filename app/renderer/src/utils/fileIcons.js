/**
 * LAZARUS CORE – fileIcons.js
 * Maps FileType enum values to Lucide icon components and color classes.
 */
import {
  Image, Film, Music, FileText, Archive, File,
  FileVideo, FileAudio, FileImage,
} from 'lucide-react';

// Matches the FileType enum in types.h
export const FILE_TYPE = {
  UNKNOWN:  0,
  IMAGE:    1,
  VIDEO:    2,
  AUDIO:    3,
  DOCUMENT: 4,
  ARCHIVE:  5,
  OTHER:    6,
};

export const FILE_TYPE_ICON = {
  [FILE_TYPE.UNKNOWN]:  File,
  [FILE_TYPE.IMAGE]:    Image,
  [FILE_TYPE.VIDEO]:    Film,
  [FILE_TYPE.AUDIO]:    Music,
  [FILE_TYPE.DOCUMENT]: FileText,
  [FILE_TYPE.ARCHIVE]:  Archive,
  [FILE_TYPE.OTHER]:    File,
};

export const FILE_TYPE_COLOR = {
  [FILE_TYPE.UNKNOWN]:  'text-text-dim',
  [FILE_TYPE.IMAGE]:    'text-blue-400',
  [FILE_TYPE.VIDEO]:    'text-purple-400',
  [FILE_TYPE.AUDIO]:    'text-green-400',
  [FILE_TYPE.DOCUMENT]: 'text-yellow-400',
  [FILE_TYPE.ARCHIVE]:  'text-orange-400',
  [FILE_TYPE.OTHER]:    'text-text-dim',
};

export const FILE_TYPE_LABEL = {
  [FILE_TYPE.UNKNOWN]:  'Unknown',
  [FILE_TYPE.IMAGE]:    'Image',
  [FILE_TYPE.VIDEO]:    'Video',
  [FILE_TYPE.AUDIO]:    'Audio',
  [FILE_TYPE.DOCUMENT]: 'Document',
  [FILE_TYPE.ARCHIVE]:  'Archive',
  [FILE_TYPE.OTHER]:    'Other',
};

/**
 * Returns the Lucide icon component for a given FileType id.
 */
export function iconForType(typeId) {
  return FILE_TYPE_ICON[typeId] ?? File;
}

/**
 * Returns the Tailwind color class for a given FileType id.
 */
export function colorForType(typeId) {
  return FILE_TYPE_COLOR[typeId] ?? 'text-text-dim';
}

/**
 * Returns a human-readable label for a given FileType id.
 */
export function labelForType(typeId) {
  return FILE_TYPE_LABEL[typeId] ?? 'Unknown';
}

// Extension → FileType mapping (client-side fallback)
const EXT_MAP = {
  jpg: FILE_TYPE.IMAGE, jpeg: FILE_TYPE.IMAGE, png: FILE_TYPE.IMAGE,
  gif: FILE_TYPE.IMAGE, bmp: FILE_TYPE.IMAGE,  webp: FILE_TYPE.IMAGE,
  tiff: FILE_TYPE.IMAGE, tif: FILE_TYPE.IMAGE, heic: FILE_TYPE.IMAGE,
  raw: FILE_TYPE.IMAGE,  cr2: FILE_TYPE.IMAGE,  nef: FILE_TYPE.IMAGE,

  mp4: FILE_TYPE.VIDEO, avi: FILE_TYPE.VIDEO, mov: FILE_TYPE.VIDEO,
  mkv: FILE_TYPE.VIDEO, wmv: FILE_TYPE.VIDEO, flv: FILE_TYPE.VIDEO,
  webm: FILE_TYPE.VIDEO, m4v: FILE_TYPE.VIDEO, '3gp': FILE_TYPE.VIDEO,

  mp3: FILE_TYPE.AUDIO, wav: FILE_TYPE.AUDIO, flac: FILE_TYPE.AUDIO,
  aac: FILE_TYPE.AUDIO, ogg: FILE_TYPE.AUDIO,  wma: FILE_TYPE.AUDIO,
  m4a: FILE_TYPE.AUDIO, aiff: FILE_TYPE.AUDIO,

  pdf: FILE_TYPE.DOCUMENT, doc: FILE_TYPE.DOCUMENT, docx: FILE_TYPE.DOCUMENT,
  xls: FILE_TYPE.DOCUMENT, xlsx: FILE_TYPE.DOCUMENT, ppt: FILE_TYPE.DOCUMENT,
  pptx: FILE_TYPE.DOCUMENT, txt: FILE_TYPE.DOCUMENT,  rtf: FILE_TYPE.DOCUMENT,

  zip: FILE_TYPE.ARCHIVE, rar: FILE_TYPE.ARCHIVE, '7z': FILE_TYPE.ARCHIVE,
  tar: FILE_TYPE.ARCHIVE, gz: FILE_TYPE.ARCHIVE,  bz2: FILE_TYPE.ARCHIVE,
};

export function typeFromExtension(ext) {
  return EXT_MAP[(ext || '').toLowerCase()] ?? FILE_TYPE.UNKNOWN;
}
