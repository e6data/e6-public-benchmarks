import java.nio.file.*
import java.nio.charset.StandardCharsets
import java.util.Collections

log.info("🚀 Starting JSR223 Query File Loader...")

def queryPath = props.get("QUERY_PATH")
def queryFile = Paths.get(queryPath).toFile()

if (!queryFile.exists() || !queryFile.canRead()) {
    log.error("ERROR: Query file not found/unreadable: " + queryPath)
    throw new IllegalArgumentException("Invalid query file: " + queryPath)
}

log.info("📁 Loading query file: " + queryPath)

def fileContent = new String(Files.readAllBytes(queryFile.toPath()), StandardCharsets.UTF_8)
def queries = []

// Process CSV format
if (queryPath.toLowerCase().endsWith('.csv')) {
    log.info("🔍 Processing CSV format file...")
    def lines = fileContent.split('\n')
    def skipHeader = true
    
    for (line in lines) {
        line = line.trim()
        if (!line || line.startsWith('#')) continue
        
        // Skip header if it contains QUERY_ALIAS,QUERY
        if (skipHeader && line.toUpperCase().contains('QUERY_ALIAS')) {
            log.info("📋 Skipping CSV header")
            skipHeader = false
            continue
        }
        skipHeader = false
        
        // Split by comma - simple approach
        def parts = line.split(',', 2)
        if (parts.length >= 2) {
            def queryAlias = parts[0].trim()
            def queryText = parts[1].trim()
            
            // Remove quotes if present
            if (queryText.startsWith('"') && queryText.endsWith('"')) {
                queryText = queryText.substring(1, queryText.length() - 1)
            }
            
            // Clean query - remove comments and normalize whitespace
            queryText = queryText.replaceAll(/--.*?(\n|$)/, ' ')  // Remove -- comments
            queryText = queryText.replaceAll(/\/\*[\s\S]*?\*\//, ' ')  // Remove /* */ comments
            queryText = queryText.replaceAll(/\s+/, ' ').trim()
            
            if (queryText && queryAlias) {
                queries.add([alias: queryAlias, query: queryText])
                log.info("✅ Loaded query: ${queryAlias}")
            }
        }
    }
}

log.info("✅ Loaded ${queries.size()} queries from file")

if (queries.size() == 0) {
    log.error("❌ No valid queries found in file: " + queryPath)
    throw new IllegalArgumentException("No valid queries found")
}

// Shuffle if requested
if ("true".equalsIgnoreCase(props.get("RANDOM_ORDER"))) {
    log.info("🔀 Shuffling queries...")
    Collections.shuffle(queries)
}

// Store globally
props.put("LOADED_QUERIES", queries)
props.put("QUERY_COUNT", queries.size())
props.put("QUERIES_LOADED", "true")

log.info("🎯 Setup complete: ${queries.size()} queries ready for execution")