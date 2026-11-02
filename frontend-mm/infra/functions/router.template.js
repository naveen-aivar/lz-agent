// CloudFront Function, viewer-request, runtime cloudfront-js-2.0 (strict mode; kept to ES5 style on purpose).
// Source: infra/functions/router.template.js. infra/render.py fills CONFIG from the agents' manifest.json files:
//   { "api": [ { "prefix": "/agents/x/api/", "origin": "/api/" } ] }          longest prefix first
// Order of the rules (the first that applies decides):
//   1. API proxy: /agents/<id>/api/... -> <originPath>... (the behaviour already picked that API's origin).
//   2. Anything else under /agents/<id>/ is a static file of the site (images, samples ...): S3 gets the path as it is,
//      a missing file is a real 404. There is no app at /agents/<id>/ any more, so no index.html is added there.
//   3. Everything else is the dashboard, one page: a path without a file extension is /index.html (this includes
//      /agents and /agents/, which name no agent). A path whose last segment has a dot is a file and is left alone.
var CONFIG = __CONFIG__;

// "." / ".." segments, also percent-encoded: after the prefix swap they would climb out of originPath.
var DOT_SEGMENT = /(^|\/)(\.|%2e){1,2}(\/|$)/i;

function hasExtension(uri) {
  return uri.substring(uri.lastIndexOf('/') + 1).indexOf('.') !== -1;
}

function handler(event) {
  var request = event.request;
  var uri = request.uri;

  for (var i = 0; i < CONFIG.api.length; i++) {
    if (uri.indexOf(CONFIG.api[i].prefix) === 0) {
      var rest = uri.substring(CONFIG.api[i].prefix.length);
      if (DOT_SEGMENT.test(rest)) {
        return { statusCode: 400, statusDescription: 'Bad Request' };
      }
      request.uri = CONFIG.api[i].origin + rest;
      return request;
    }
  }

  if (uri.indexOf('/agents/') === 0 && uri.length > 8) {
    return request;
  }

  if (!hasExtension(uri)) {
    request.uri = '/index.html';
  }
  return request;
}
