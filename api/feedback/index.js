const { TableClient } = require('@azure/data-tables');

const TABLE = 'feedbackCounts';
const PAGE_RE = /^[A-Za-z0-9/_.\-]{1,256}$/;
const REACTIONS = new Set(['like', 'dislike']);

// Table-already-exists is the only createTable error we can safely ignore;
// everything else (401/403/network) must surface so the caller sees a 500.
function isTableExistsError(err) {
  return err && (err.statusCode === 409 || err.code === 'TableAlreadyExists');
}

module.exports = async function (context, req) {
  try {
    const page = req.body && req.body.page;
    const reaction = req.body && req.body.reaction;

    if (!page || !PAGE_RE.test(page) || !REACTIONS.has(reaction)) {
      context.res = { status: 400, body: { error: 'bad request' } };
      return;
    }

    const conn = process.env.FEEDBACK_STORAGE_CONN;
    if (!conn) {
      context.log.error('FEEDBACK_STORAGE_CONN not set');
      context.res = { status: 500, body: { error: 'storage not configured' } };
      return;
    }

    const client = TableClient.fromConnectionString(conn, TABLE);
    try {
      await client.createTable();
    } catch (err) {
      if (!isTableExistsError(err)) {
        context.log.error('createTable failed', err);
        throw err;
      }
    }

    const pk = encodeURIComponent(page);
    const rk = reaction;

    for (let i = 0; i < 3; i++) {
      try {
        const entity = await client.getEntity(pk, rk);
        entity.count = (entity.count || 0) + 1;
        await client.updateEntity(entity, 'Replace', { etag: entity.etag });
        context.res = { status: 200, body: { ok: true } };
        return;
      } catch (e) {
        if (e.statusCode === 404) {
          try {
            await client.createEntity({ partitionKey: pk, rowKey: rk, count: 1 });
            context.res = { status: 200, body: { ok: true } };
            return;
          } catch (ce) {
            if (ce.statusCode !== 409) {
              context.log.error('createEntity failed', ce);
              throw ce;
            }
          }
        } else if (e.statusCode !== 412) {
          context.log.error('updateEntity failed', e);
          throw e;
        }
      }
    }

    context.res = { status: 503, body: { error: 'contention, try again' } };
  } catch (err) {
    context.log.error('feedback handler failed', err);
    context.res = {
      status: 500,
      body: { error: 'internal error', code: err && err.code ? err.code : undefined },
    };
  }
};
