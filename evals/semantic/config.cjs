'use strict';

const fs = require('node:fs');
const path = require('node:path');

function configuration(suite, mode) {
  if (!['retrieval', 'answer'].includes(suite) || !['offline_fixture', 'local_model'].includes(mode)) {
    throw new Error('Unknown semantic evaluation suite or mode');
  }
  const corpus = JSON.parse(fs.readFileSync(path.join(__dirname, 'cases.json'), 'utf8'));
  if (corpus.schema_version !== 1 || !Array.isArray(corpus.cases) || corpus.cases.length === 0) {
    throw new Error('The complete fixed synthetic corpus is required');
  }
  const identifiers = corpus.cases.map((test) => test.id);
  if (identifiers.some((id) => typeof id !== 'string' || !id.length) || new Set(identifiers).size !== identifiers.length) {
    throw new Error('Every synthetic case must have a unique identifier');
  }
  const providerConfig = { suite, mode };
  if (mode === 'local_model') {
    const profile = process.env.DSC_SEMANTIC_PROFILE;
    if (!profile || !path.isAbsolute(profile)) {
      throw new Error('NOT_RUN: an explicit absolute local model profile is required');
    }
    providerConfig.profile_path = profile;
  }
  return {
    description: `意味記憶 ${suite} / ${mode}（合成データのみ）`,
    sharing: false,
    prompts: ['{{case_id}}'],
    providers: [{
      id: `file://${path.join(__dirname, 'provider.py')}`,
      label: 'core-semantic',
      config: providerConfig,
    }],
    defaultTest: {
      options: { disableConversationVar: true, disableVarExpansion: true },
      assert: [{
        type: 'javascript',
        metric: 'semantic-hard-gates',
        value: `file://${path.join(__dirname, 'assertions.cjs')}`,
      }],
    },
    tests: identifiers.map((id) => ({ description: id, vars: { case_id: id } })),
    evaluateOptions: { maxConcurrency: 1 },
  };
}

module.exports = { configuration };
