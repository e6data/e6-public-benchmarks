import java.io.*;
import java.sql.*;
import java.util.*;
import java.time.LocalDateTime;
import java.time.format.DateTimeFormatter;

/**
 * Universal JDBC Test Driver
 * Tests database connectivity and executes queries based on properties file configuration
 * Supports multiple database engines: E6Data, DBR, Trino, Presto, Athena, etc.
 * 
 * Usage: java TestDriver <connection_properties_file> [test_query]
 */
public class TestDriver {
    
    private static final String DEFAULT_TEST_QUERY = "SELECT 1 as test_connection";
    private static final int DEFAULT_QUERY_TIMEOUT = 30; // seconds
    
    // ANSI color codes for console output
    private static final String GREEN = "\u001B[32m";
    private static final String RED = "\u001B[31m";
    private static final String BLUE = "\u001B[34m";
    private static final String YELLOW = "\u001B[33m";
    private static final String RESET = "\u001B[0m";
    private static final String BOLD = "\u001B[1m";
    
    private Properties connectionProps;
    private String propertiesFile;
    
    public static void main(String[] args) {
        if (args.length < 1) {
            printUsage();
            System.exit(1);
        }
        
        TestDriver driver = new TestDriver();
        String propertiesFile = args[0];
        String testQuery = args.length > 1 ? args[1] : DEFAULT_TEST_QUERY;
        
        try {
            driver.loadProperties(propertiesFile);
            driver.runConnectivityTest(testQuery);
        } catch (Exception e) {
            System.err.println(RED + "❌ Test failed: " + e.getMessage() + RESET);
            e.printStackTrace();
            System.exit(1);
        }
    }
    
    private static void printUsage() {
        System.out.println(BOLD + "Universal JDBC Test Driver" + RESET);
        System.out.println("========================================");
        System.out.println("Usage: java TestDriver <properties_file> [test_query]");
        System.out.println("");
        System.out.println("Examples:");
        System.out.println("  java TestDriver connection_properties/e6_connection.properties");
        System.out.println("  java TestDriver connection_properties/dbr_connection.properties \"SELECT current_timestamp()\"");
        System.out.println("");
        System.out.println("Properties file should contain:");
        System.out.println("  DRIVER_CLASS=<jdbc.driver.class>");
        System.out.println("  CONNECTION_STRING=<jdbc:url>");
        System.out.println("  USER=<username>");
        System.out.println("  PASSWORD=<password>");
    }
    
    private void loadProperties(String propertiesFile) throws IOException {
        this.propertiesFile = propertiesFile;
        this.connectionProps = new Properties();
        
        try (FileInputStream fis = new FileInputStream(propertiesFile)) {
            connectionProps.load(fis);
            System.out.println(BLUE + "📋 Loaded properties from: " + propertiesFile + RESET);
        } catch (FileNotFoundException e) {
            throw new IOException("Properties file not found: " + propertiesFile);
        }
        
        // Validate required properties
        validateRequiredProperties();
    }
    
    private void validateRequiredProperties() throws IllegalArgumentException {
        String[] requiredProps = {"DRIVER_CLASS", "CONNECTION_STRING"};
        
        for (String prop : requiredProps) {
            String value = connectionProps.getProperty(prop);
            if (value == null || value.trim().isEmpty()) {
                throw new IllegalArgumentException("Required property '" + prop + "' is missing or empty in " + propertiesFile);
            }
        }
    }
    
    private void runConnectivityTest(String testQuery) throws Exception {
        String driverClass = connectionProps.getProperty("DRIVER_CLASS");
        String connectionString = connectionProps.getProperty("CONNECTION_STRING");
        String user = connectionProps.getProperty("USER", "");
        String password = connectionProps.getProperty("PASSWORD", "");
        
        printTestHeader(driverClass, connectionString);
        
        // Step 1: Load JDBC Driver
        loadJdbcDriver(driverClass);
        
        // Step 2: Test Database Connection
        testDatabaseConnection(connectionString, user, password, testQuery);
        
        System.out.println(GREEN + "✅ All connectivity tests passed successfully!" + RESET);
    }
    
    private void printTestHeader(String driverClass, String connectionString) {
        System.out.println("\n" + BOLD + "================================================================================");
        System.out.println("🚀 JDBC Connectivity Test");
        System.out.println("================================================================================" + RESET);
        System.out.println(BLUE + "📅 Test Time: " + getCurrentTimestamp() + RESET);
        System.out.println(BLUE + "🏷️  Driver Class: " + driverClass + RESET);
        System.out.println(BLUE + "🔗 Connection URL: " + maskSensitiveInfo(connectionString) + RESET);
        System.out.println(BLUE + "👤 Username: " + connectionProps.getProperty("USER", "<not specified>") + RESET);
        System.out.println();
    }
    
    private void loadJdbcDriver(String driverClass) throws ClassNotFoundException {
        System.out.println(YELLOW + "🔧 Loading JDBC Driver..." + RESET);
        
        try {
            Class.forName(driverClass);
            System.out.println(GREEN + "✅ Successfully loaded driver: " + driverClass + RESET);
            
            // Print driver information
            printDriverInfo(driverClass);
            
        } catch (ClassNotFoundException e) {
            System.out.println(RED + "❌ Failed to load JDBC driver: " + driverClass + RESET);
            System.out.println(RED + "   Make sure the driver JAR is in the classpath" + RESET);
            throw e;
        }
    }
    
    private void printDriverInfo(String driverClass) {
        try {
            Driver driver = DriverManager.getDriver("jdbc:test:");
        } catch (Exception e) {
            // Ignore - just trying to get driver info
        }
        
        try {
            Driver driver = (Driver) Class.forName(driverClass).newInstance();
            System.out.println(BLUE + "   Driver Version: " + driver.getMajorVersion() + "." + driver.getMinorVersion() + RESET);
        } catch (Exception e) {
            // Driver info not available
        }
    }
    
    private void testDatabaseConnection(String connectionString, String user, String password, String testQuery) 
            throws SQLException {
        
        System.out.println(YELLOW + "🔌 Testing database connection..." + RESET);
        
        Connection connection = null;
        Statement statement = null;
        ResultSet resultSet = null;
        
        try {
            // Establish connection
            long connectionStart = System.currentTimeMillis();
            
            if (user.isEmpty() && password.isEmpty()) {
                connection = DriverManager.getConnection(connectionString);
            } else {
                connection = DriverManager.getConnection(connectionString, user, password);
            }
            
            long connectionTime = System.currentTimeMillis() - connectionStart;
            System.out.println(GREEN + "✅ Connected successfully (" + connectionTime + "ms)" + RESET);
            
            // Print connection metadata
            printConnectionMetadata(connection);
            
            // Execute test query
            executeTestQuery(connection, testQuery);
            
        } catch (SQLException e) {
            System.out.println(RED + "❌ Connection failed: " + e.getMessage() + RESET);
            System.out.println(RED + "   SQL State: " + e.getSQLState() + RESET);
            System.out.println(RED + "   Error Code: " + e.getErrorCode() + RESET);
            throw e;
        } finally {
            // Clean up resources
            closeResources(resultSet, statement, connection);
        }
    }
    
    private void printConnectionMetadata(Connection connection) {
        try {
            DatabaseMetaData metaData = connection.getMetaData();
            System.out.println(BLUE + "   Database: " + metaData.getDatabaseProductName() + 
                             " " + metaData.getDatabaseProductVersion() + RESET);
            System.out.println(BLUE + "   JDBC URL: " + maskSensitiveInfo(metaData.getURL()) + RESET);
            System.out.println(BLUE + "   JDBC Driver: " + metaData.getDriverName() + 
                             " " + metaData.getDriverVersion() + RESET);
        } catch (SQLException e) {
            System.out.println(YELLOW + "   (Database metadata not available)" + RESET);
        }
    }
    
    private void executeTestQuery(Connection connection, String testQuery) throws SQLException {
        System.out.println(YELLOW + "🔍 Executing test query..." + RESET);
        System.out.println(BLUE + "   Query: " + testQuery + RESET);
        
        Statement statement = null;
        ResultSet resultSet = null;
        
        try {
            statement = connection.createStatement();
            statement.setQueryTimeout(DEFAULT_QUERY_TIMEOUT);
            
            long queryStart = System.currentTimeMillis();
            resultSet = statement.executeQuery(testQuery);
            long queryTime = System.currentTimeMillis() - queryStart;
            
            // Process results
            ResultSetMetaData rsMetaData = resultSet.getMetaData();
            int columnCount = rsMetaData.getColumnCount();
            
            System.out.println(GREEN + "✅ Query executed successfully (" + queryTime + "ms)" + RESET);
            System.out.println(BLUE + "   Columns: " + columnCount + RESET);
            
            // Print column names
            System.out.print(BLUE + "   Column Names: ");
            for (int i = 1; i <= columnCount; i++) {
                System.out.print(rsMetaData.getColumnName(i));
                if (i < columnCount) System.out.print(", ");
            }
            System.out.println(RESET);
            
            // Print first few rows
            int rowCount = 0;
            System.out.println(BLUE + "   Sample Results:" + RESET);
            while (resultSet.next() && rowCount < 3) {
                System.out.print(BLUE + "     Row " + (rowCount + 1) + ": ");
                for (int i = 1; i <= columnCount; i++) {
                    Object value = resultSet.getObject(i);
                    System.out.print(value != null ? value.toString() : "NULL");
                    if (i < columnCount) System.out.print(" | ");
                }
                System.out.println(RESET);
                rowCount++;
            }
            
            // Count remaining rows if any
            while (resultSet.next()) {
                rowCount++;
            }
            
            System.out.println(GREEN + "   Total rows returned: " + rowCount + RESET);
            
        } catch (SQLException e) {
            System.out.println(RED + "❌ Query execution failed: " + e.getMessage() + RESET);
            System.out.println(RED + "   SQL State: " + e.getSQLState() + RESET);
            throw e;
        } finally {
            closeResources(resultSet, statement, null);
        }
    }
    
    private void closeResources(ResultSet rs, Statement stmt, Connection conn) {
        try {
            if (rs != null) rs.close();
        } catch (SQLException e) {
            System.err.println("Error closing ResultSet: " + e.getMessage());
        }
        
        try {
            if (stmt != null) stmt.close();
        } catch (SQLException e) {
            System.err.println("Error closing Statement: " + e.getMessage());
        }
        
        try {
            if (conn != null) {
                System.out.println(YELLOW + "🔌 Closing database connection..." + RESET);
                conn.close();
                System.out.println(GREEN + "✅ Connection closed successfully" + RESET);
            }
        } catch (SQLException e) {
            System.err.println("Error closing Connection: " + e.getMessage());
        }
    }
    
    private String getCurrentTimestamp() {
        return LocalDateTime.now().format(DateTimeFormatter.ofPattern("yyyy-MM-dd HH:mm:ss"));
    }
    
    private String maskSensitiveInfo(String url) {
        if (url == null) return "<null>";
        
        // Mask password in JDBC URL
        return url.replaceAll("(?i)(password=)[^;&]*", "$1***")
                 .replaceAll("(?i)(pwd=)[^;&]*", "$1***");
    }
}