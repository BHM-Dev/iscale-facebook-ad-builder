import React from 'react';
import { useNavigate } from 'react-router-dom';
import { ArrowRight, FileImage, FolderOpen, BookOpen } from 'lucide-react';

const TOOLS = [
  { path: '/generated-ads', icon: FileImage, title: 'Generated Ads', description: 'Review and manage the image and video creatives you have generated.' },
  { path: '/creative-library', icon: FolderOpen, title: 'Drive Imports', description: 'Browse creative references imported from Drive.' },
  { path: '/copy-library', icon: BookOpen, title: 'Copy Library', description: 'Save and reuse copy that is ready for future campaigns.' },
];

export default function LibrariesHub() {
  const navigate = useNavigate();
  return (
    <div className="max-w-5xl mx-auto">
      <div className="mb-8"><h1 className="text-3xl font-bold text-gray-900">Libraries</h1><p className="text-gray-600 mt-2">Find your saved creative and copy assets</p></div>
      <div className="grid grid-cols-1 md:grid-cols-3 gap-6">
        {TOOLS.map(tool => { const Icon = tool.icon; return <button key={tool.path} onClick={() => navigate(tool.path)} className="group relative flex flex-col items-start p-8 bg-white rounded-2xl border-2 border-gray-100 hover:border-gray-300 hover:shadow-xl transition-all duration-300 text-left"><div className="w-14 h-14 bg-gray-100 rounded-2xl flex items-center justify-center mb-5 group-hover:scale-110 transition-transform duration-300"><Icon size={28} className="text-gray-700" /></div><h3 className="text-xl font-bold text-gray-900 mb-2">{tool.title}</h3><p className="text-gray-500 text-sm leading-relaxed flex-1">{tool.description}</p><div className="mt-6 flex items-center gap-2 text-sm font-semibold text-gray-900 group-hover:gap-3 transition-all">Open <ArrowRight size={16} /></div></button>; })}
      </div>
    </div>
  );
}
