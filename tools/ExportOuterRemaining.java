// 使用本地Ghidra默认分析导出原外层剩余函数；不运行目标、不改写输入PE。
import ghidra.app.script.GhidraScript;
import ghidra.app.decompiler.DecompInterface;
import ghidra.app.decompiler.DecompileOptions;
import ghidra.app.decompiler.DecompileResults;
import ghidra.program.model.listing.Function;
import java.nio.file.Files;
import java.nio.file.Path;
import java.nio.charset.StandardCharsets;
import java.util.ArrayList;

public class ExportOuterRemaining extends GhidraScript {
    public void run() throws Exception {
        Path output=Path.of(getScriptArgs()[0]);
        Files.createDirectory(output);
        ArrayList<String> lines=new ArrayList<>();
        lines.add("rva\taddress\tname\texternal\tstatus");
        DecompInterface decompiler=new DecompInterface();
        int written=0,failed=0;
        try {
            decompiler.setOptions(new DecompileOptions());
            decompiler.toggleCCode(true);
            decompiler.toggleSyntaxTree(false);
            if(!decompiler.openProgram(currentProgram)) throw new Exception(decompiler.getLastMessage());
            for(Function function:currentProgram.getFunctionManager().getFunctions(true)) {
                monitor.checkCancelled();
                long rva=function.getEntryPoint().subtract(currentProgram.getImageBase());
                String address=function.getEntryPoint().toString();
                String status="prior-range";
                if(function.isExternal()) status="external";
                else if(rva>=0x6000) {
                    DecompileResults result=decompiler.decompileFunction(function,30,monitor);
                    if(result.decompileCompleted() && result.getDecompiledFunction()!=null) {
                        Files.writeString(output.resolve("0x"+address+".c"),
                            "// Ghidra默认分析伪代码；不是原源码。\n"+result.getDecompiledFunction().getC(),StandardCharsets.UTF_8);
                        status="written";written++;
                    } else {
                        status="failed:"+result.getErrorMessage().replace('\n',' ').replace('\t',' ');failed++;
                    }
                }
                lines.add("0x"+Long.toHexString(rva)+"\t0x"+address+"\t"+
                    function.getName().replace('\t',' ')+"\t"+function.isExternal()+"\t"+status);
                Files.write(output.resolve("functions.tsv"),lines,StandardCharsets.UTF_8);
            }
        } finally {decompiler.dispose();}
        println("OUTER_REMAINING written="+written+" failed="+failed+" inventory="+(lines.size()-1));
    }
}
