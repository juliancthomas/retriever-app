SELECT 
    d.filename,
    d.document_type,
    c.chunk_index,
    c.content,
    1 - (c.embedding <=> $1) AS similarity_score
FROM document_chunks c
JOIN documents d ON c.document_id = d.id
WHERE d.document_type = 'medical_record'
ORDER BY c.embedding <=> $1
LIMIT 5;