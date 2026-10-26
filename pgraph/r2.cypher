// R2 in Cypher: executed grants on the patent whose field, territory, and term overlap the request, as recorded by
// the cutoff and not superseded by then. Field and territory overlap run in both directions along BROADER.
MATCH (g:ExecutedGrant)-[:ABOUT]->(:Patent {key: $patent})
WHERE g.graph = 'approved'
  AND g.recordedAt <= datetime($cutoff)
  AND (g.supersededAt IS NULL OR g.supersededAt > datetime($cutoff))
  AND g.validFrom <= date($end) AND g.validTo >= date($start)
MATCH (g)-[:FIELD]->(gf:Field), (g)-[:TERRITORY]->(gt:Territory)
MATCH (rf:Field {id: $field}), (rt:Territory {id: $territory})
WHERE (EXISTS { (rf)-[:BROADER*0..]->(gf) } OR EXISTS { (gf)-[:BROADER*1..]->(rf) })
  AND (EXISTS { (rt)-[:BROADER*0..]->(gt) } OR EXISTS { (gt)-[:BROADER*1..]->(rt) })
OPTIONAL MATCH (g)-[:LICENSEE]->(l:Licensee)
RETURN DISTINCT g.id AS grant, g.exclusivity AS exclusivity, gf.id AS field, gt.id AS territory,
       toString(g.validFrom) AS from, toString(g.validTo) AS to, g.cap AS cap, l.name AS name
ORDER BY grant
